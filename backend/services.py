from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Set, Tuple
from .database import get_db_connection, convert_query_for_engine

def parse_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()

def get_holidays_set() -> Set[str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT date FROM holidays")
    rows = cursor.fetchall()
    conn.close()
    return {row["date"] if isinstance(row, dict) or hasattr(row, 'keys') else row[0] for row in rows}

def calculate_business_days(start_date_str: str, end_date_str: str) -> int:
    """Calcula os dias úteis entre duas datas excluindo fins de semana e feriados."""
    try:
        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)
    except Exception:
        return 0

    if start_date > end_date:
        return 0

    holidays = get_holidays_set()
    current = start_date
    business_days = 0

    while current <= end_date:
        iso_str = current.strftime("%Y-%m-%d")
        if current.weekday() < 5 and iso_str not in holidays:
            business_days += 1
        current += timedelta(days=1)

    return business_days

def get_user_balances(user_id: int, year: int = None) -> Dict[str, Any]:
    if year is None:
        year = date.today().year

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(convert_query_for_engine("SELECT * FROM users WHERE id = ?"), (user_id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return {}

    user_dict = dict(user)
    total_entitlement = user_dict.get("total_vacation_days", 22)
    year_prefix = f"{year}%"

    # Férias aprovadas no ano (apenas 'aprovado' debita o saldo)
    cursor.execute(convert_query_for_engine("""
    SELECT SUM(business_days) as approved_days
    FROM leave_requests
    WHERE user_id = ? AND status = 'aprovado' AND type = 'ferias'
      AND (start_date LIKE ? OR end_date LIKE ?)
    """), (user_id, year_prefix, year_prefix))
    row_approved = cursor.fetchone()
    approved_vacation = dict(row_approved).get("approved_days") or 0 if row_approved else 0

    # Férias pendentes no ano (inclui pendente e cancelamento_pendente)
    cursor.execute(convert_query_for_engine("""
    SELECT SUM(business_days) as pending_days
    FROM leave_requests
    WHERE user_id = ? AND status = 'pendente' AND type = 'ferias'
      AND (start_date LIKE ? OR end_date LIKE ?)
    """), (user_id, year_prefix, year_prefix))
    row_pending = cursor.fetchone()
    pending_vacation = dict(row_pending).get("pending_days") or 0 if row_pending else 0

    # Outras ausências aprovadas
    cursor.execute(convert_query_for_engine("""
    SELECT type, SUM(business_days) as days
    FROM leave_requests
    WHERE user_id = ? AND status = 'aprovado' AND type != 'ferias'
      AND (start_date LIKE ? OR end_date LIKE ?)
    GROUP BY type
    """), (user_id, year_prefix, year_prefix))
    other_leaves = {dict(r)["type"]: dict(r)["days"] for r in cursor.fetchall()}

    remaining_vacation = max(0, total_entitlement - approved_vacation)

    conn.close()
    return {
        "user_id": user_id,
        "name": user_dict.get("name"),
        "year": year,
        "total_days": total_entitlement,
        "approved_days": approved_vacation,
        "pending_days": pending_vacation,
        "remaining_days": remaining_vacation,
        "other_leaves": other_leaves
    }

def detect_conflicts(user_id: int, start_date_str: str, end_date_str: str, exclude_request_id: int = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(convert_query_for_engine("SELECT department_id, name FROM users WHERE id = ?"), (user_id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return []

    user_dict = dict(user)
    dept_id = user_dict.get("department_id")
    if not dept_id:
        conn.close()
        return []

    query = """
    SELECT lr.id, lr.start_date, lr.end_date, lr.type, lr.status, u.id as user_id, u.name as user_name, u.job_title, d.name as dept_name
    FROM leave_requests lr
    JOIN users u ON lr.user_id = u.id
    JOIN departments d ON u.department_id = d.id
    WHERE u.department_id = ?
      AND u.id != ?
      AND lr.status IN ('aprovado', 'pendente', 'cancelamento_pendente')
      AND (
        (lr.start_date <= ? AND lr.end_date >= ?) OR
        (lr.start_date >= ? AND lr.start_date <= ?) OR
        (lr.end_date >= ? AND lr.end_date <= ?)
      )
    """
    params = [dept_id, user_id, end_date_str, start_date_str, start_date_str, end_date_str, start_date_str, end_date_str]

    if exclude_request_id:
        query += " AND lr.id != ?"
        params.append(exclude_request_id)

    cursor.execute(convert_query_for_engine(query), params)
    conflicts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return conflicts

def get_dashboard_stats(current_user_id: int, role: str, department_id: int = None) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    today_str = date.today().strftime("%Y-%m-%d")

    cursor.execute("SELECT COUNT(*) as total FROM users WHERE is_active = TRUE")
    row_t = cursor.fetchone()
    total_users = dict(row_t).get("total", 0) if row_t else 0

    # Ausentes hoje
    cursor.execute(convert_query_for_engine("""
    SELECT lr.*, u.name as user_name, u.avatar_color, d.name as dept_name
    FROM leave_requests lr
    JOIN users u ON lr.user_id = u.id
    JOIN departments d ON u.department_id = d.id
    WHERE lr.status = 'aprovado'
      AND lr.start_date <= ? AND lr.end_date >= ?
    """), (today_str, today_str))
    absent_today = [dict(row) for row in cursor.fetchall()]

    # Pedidos a aguardar aprovação (novos pedidos 'pendente' ou pedidos de anulação 'cancelamento_pendente')
    if role == 'admin':
        cursor.execute("""
        SELECT lr.*, u.name as user_name, u.avatar_color, u.job_title, d.name as dept_name
        FROM leave_requests lr
        JOIN users u ON lr.user_id = u.id
        JOIN departments d ON u.department_id = d.id
        WHERE lr.status IN ('pendente', 'cancelamento_pendente')
        ORDER BY lr.created_at ASC
        """)
    elif role == 'gestor' and department_id:
        cursor.execute(convert_query_for_engine("""
        SELECT lr.*, u.name as user_name, u.avatar_color, u.job_title, d.name as dept_name
        FROM leave_requests lr
        JOIN users u ON lr.user_id = u.id
        JOIN departments d ON u.department_id = d.id
        WHERE lr.status IN ('pendente', 'cancelamento_pendente') AND u.department_id = ?
        ORDER BY lr.created_at ASC
        """), (department_id,))
    else:
        cursor.execute(convert_query_for_engine("""
        SELECT lr.*, u.name as user_name, u.avatar_color, u.job_title, d.name as dept_name
        FROM leave_requests lr
        JOIN users u ON lr.user_id = u.id
        JOIN departments d ON u.department_id = d.id
        WHERE lr.status IN ('pendente', 'cancelamento_pendente') AND lr.user_id = ?
        ORDER BY lr.created_at ASC
        """), (current_user_id,))
    pending_requests = [dict(row) for row in cursor.fetchall()]

    # Próximas ausências
    next_month_str = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")
    cursor.execute(convert_query_for_engine("""
    SELECT lr.*, u.name as user_name, u.avatar_color, d.name as dept_name
    FROM leave_requests lr
    JOIN users u ON lr.user_id = u.id
    JOIN departments d ON u.department_id = d.id
    WHERE lr.status = 'aprovado'
      AND lr.start_date >= ? AND lr.start_date <= ?
    ORDER BY lr.start_date ASC
    LIMIT 10
    """), (today_str, next_month_str))
    upcoming_leaves = [dict(row) for row in cursor.fetchall()]

    conn.close()

    user_balance = get_user_balances(current_user_id) if current_user_id else None

    return {
        "total_users": total_users,
        "absent_today_count": len(absent_today),
        "absent_today": absent_today,
        "pending_count": len(pending_requests),
        "pending_requests": pending_requests,
        "upcoming_leaves": upcoming_leaves,
        "user_balance": user_balance
    }

def generate_csv_report() -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT lr.id, u.name as colaborador, u.email, d.name as departamento,
           lr.type as tipo, lr.start_date as data_inicio, lr.end_date as data_fim,
           lr.business_days as dias_uteis, lr.status as estado,
           lr.reason as motivo, lr.manager_comment as nota_gestor, lr.created_at
    FROM leave_requests lr
    JOIN users u ON lr.user_id = u.id
    LEFT JOIN departments d ON u.department_id = d.id
    ORDER BY lr.start_date DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["ID", "Colaborador", "Email", "Departamento", "Tipo", "Data Início", "Data Fim", "Dias Úteis", "Estado", "Motivo", "Nota Gestor", "Data Pedido"])

    for r in rows:
        row = dict(r)
        writer.writerow([
            row["id"], row["colaborador"], row["email"], row["departamento"],
            row["tipo"], row["data_inicio"], row["data_fim"], row["dias_uteis"],
            row["estado"], row["motivo"] or "", row["nota_gestor"] or "", row["created_at"]
        ])

    return output.getvalue()

def generate_ical_feed() -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT lr.id, u.name as user_name, lr.type, lr.start_date, lr.end_date, lr.reason, d.name as dept_name
    FROM leave_requests lr
    JOIN users u ON lr.user_id = u.id
    LEFT JOIN departments d ON u.department_id = d.id
    WHERE lr.status = 'aprovado'
    """)
    leaves = cursor.fetchall()
    conn.close()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Gestao Ferias Equipa//PT",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Mapa de Férias da Equipa"
    ]

    for it in leaves:
        item = dict(it)
        start_fmt = item["start_date"].replace("-", "")
        try:
            end_dt = parse_date(item["end_date"]) + timedelta(days=1)
            end_fmt = end_dt.strftime("%Y%m%d")
        except Exception:
            end_fmt = item["end_date"].replace("-", "")

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:ferias-{item['id']}@empresa.pt",
            f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART;VALUE=DATE:{start_fmt}",
            f"DTEND;VALUE=DATE:{end_fmt}",
            f"SUMMARY:[{item['type'].capitalize()}] {item['user_name']} ({item['dept_name']})",
            f"DESCRIPTION:{item['reason'] or 'Ausência programada'}",
            "STATUS:CONFIRMED",
            "END:VEVENT"
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
