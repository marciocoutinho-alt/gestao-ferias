import os
from datetime import datetime, date, timedelta
from typing import Optional, List
from fastapi import FastAPI, Request, Response, HTTPException, Query, Body, Cookie
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .database import get_db_connection, init_db, convert_query_for_engine, IS_POSTGRES
from .services import (
    calculate_business_days,
    get_user_balances,
    detect_conflicts,
    get_dashboard_stats,
    generate_csv_report,
    generate_ical_feed
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

app = FastAPI(title="Gestão de Férias da Equipa", description="API e Interface de Gestão de Férias e Ausências")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@app.on_event("startup")
def on_startup():
    init_db()

# Modelos Pydantic
class UserLogin(BaseModel):
    email: str
    password: Optional[str] = "1234"

class UserCreate(BaseModel):
    name: str
    email: str
    password: Optional[str] = "1234"
    role: str
    department_id: Optional[int] = None
    total_vacation_days: Optional[int] = 22
    job_title: Optional[str] = ""
    avatar_color: Optional[str] = "#3B82F6"

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    department_id: Optional[int] = None
    total_vacation_days: Optional[int] = None
    job_title: Optional[str] = None
    is_active: Optional[bool] = None

class DepartmentCreate(BaseModel):
    name: str
    color: Optional[str] = "#3B82F6"

class HolidayCreate(BaseModel):
    date: str
    name: str
    is_national: Optional[bool] = True

class LeaveRequestCreate(BaseModel):
    user_id: int
    type: str
    start_date: str
    end_date: str
    reason: Optional[str] = ""

class ApprovalAction(BaseModel):
    manager_comment: Optional[str] = ""

class CancelRequestAction(BaseModel):
    reason: Optional[str] = ""

# --- Rotas de Autenticação / Sessão Ativa ---

def get_current_user_from_db(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(convert_query_for_engine("""
    SELECT u.*, d.name as department_name, d.color as department_color
    FROM users u
    LEFT JOIN departments d ON u.department_id = d.id
    WHERE u.id = ? AND u.is_active = TRUE
    """), (user_id,))
    user = cursor.fetchone()
    conn.close()
    if user:
        return dict(user)
    return None

@app.get("/api/auth/current")
def get_current_user(active_user_id: Optional[int] = Cookie(default=None)):
    """Obrigatório autenticação: só devolve dados se houver sessão iniciada."""
    if not active_user_id:
        raise HTTPException(status_code=401, detail="Sessão não iniciada. Por favor faça login.")
    
    user = get_current_user_from_db(active_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Utilizador não encontrado ou inativo.")
    
    user["balances"] = get_user_balances(user["id"])
    return user

@app.post("/api/auth/login")
def login(credentials: UserLogin, response: Response):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(convert_query_for_engine("""
    SELECT * FROM users WHERE email = ? AND is_active = TRUE
    """), (credentials.email.strip().lower(),))
    user = cursor.fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Email não registado no sistema.")

    user_dict = dict(user)
    # Validação de palavra-passe
    if user_dict.get("password") and user_dict.get("password") != credentials.password:
        raise HTTPException(status_code=401, detail="Palavra-passe incorreta.")

    response.set_cookie(
        key="active_user_id",
        value=str(user_dict["id"]),
        httponly=False,
        samesite="lax",
        max_age=60*60*24*30 # 30 dias de sessão
    )
    user_dict["balances"] = get_user_balances(user_dict["id"])
    return {"message": f"Bem-vindo(a), {user_dict['name']}", "user": user_dict}

@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(key="active_user_id")
    return {"message": "Sessão terminada com sucesso"}

# --- Rotas de Utilizadores e Departamentos (Admin) ---

@app.get("/api/users")
def list_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT u.id, u.name, u.email, u.role, u.department_id, u.total_vacation_days,
           u.avatar_color, u.job_title, u.is_active, u.created_at,
           d.name as department_name, d.color as department_color
    FROM users u
    LEFT JOIN departments d ON u.department_id = d.id
    WHERE u.is_active = TRUE
    ORDER BY u.name ASC
    """)
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()

    for u in users:
        u["balances"] = get_user_balances(u["id"])

    return users

@app.post("/api/users")
def create_user(user: UserCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(convert_query_for_engine("""
        INSERT INTO users (name, email, password, role, department_id, total_vacation_days, job_title, avatar_color)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            user.name.strip(),
            user.email.strip().lower(),
            user.password or "1234",
            user.role,
            user.department_id,
            user.total_vacation_days or 22,
            user.job_title,
            user.avatar_color or "#3B82F6"
        ))
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail="Este email já se encontra registado.")
    conn.close()
    return {"message": f"Colaborador {user.name} criado com sucesso ({user.total_vacation_days or 22} dias/ano)"}

@app.put("/api/users/{user_id}")
def update_user(user_id: int, update: UserUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    fields = []
    values = []
    if update.name is not None:
        fields.append("name = ?")
        values.append(update.name.strip())
    if update.email is not None:
        fields.append("email = ?")
        values.append(update.email.strip().lower())
    if update.password is not None and update.password.strip():
        fields.append("password = ?")
        values.append(update.password.strip())
    if update.role is not None:
        fields.append("role = ?")
        values.append(update.role)
    if update.department_id is not None:
        fields.append("department_id = ?")
        values.append(update.department_id)
    if update.total_vacation_days is not None:
        fields.append("total_vacation_days = ?")
        values.append(update.total_vacation_days)
    if update.job_title is not None:
        fields.append("job_title = ?")
        values.append(update.job_title)
    if update.is_active is not None:
        fields.append("is_active = ?")
        values.append(True if update.is_active else False)

    if not fields:
        conn.close()
        return {"message": "Sem alterações"}

    values.append(user_id)
    query_str = f"UPDATE users SET {', '.join(fields)} WHERE id = ?"
    cursor.execute(convert_query_for_engine(query_str), values)
    conn.commit()
    conn.close()
    return {"message": "Dados do colaborador atualizados com sucesso"}

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(convert_query_for_engine("SELECT * FROM users WHERE id = ?"), (user_id,))
    target = cursor.fetchone()
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")

    cursor.execute(convert_query_for_engine("DELETE FROM leave_requests WHERE user_id = ?"), (user_id,))
    cursor.execute(convert_query_for_engine("DELETE FROM users WHERE id = ?"), (user_id,))
    conn.commit()
    conn.close()
    return {"message": f"Colaborador {dict(target)['name']} eliminado com sucesso"}

@app.get("/api/departments")
def list_departments():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT d.*, COUNT(u.id) as members_count
    FROM departments d
    LEFT JOIN users u ON u.department_id = d.id AND u.is_active = TRUE
    GROUP BY d.id, d.name, d.color, d.created_at
    ORDER BY d.name ASC
    """)
    depts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return depts

@app.post("/api/departments")
def create_department(dept: DepartmentCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(convert_query_for_engine("INSERT INTO departments (name, color) VALUES (?, ?)"), (dept.name, dept.color))
    conn.commit()
    conn.close()
    return {"message": "Departamento criado com sucesso"}

# --- Rotas de Feriados ---

@app.get("/api/holidays")
def list_holidays():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM holidays ORDER BY date ASC")
    holidays = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return holidays

@app.post("/api/holidays")
def add_holiday(holiday: HolidayCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(convert_query_for_engine("INSERT INTO holidays (date, name, is_national) VALUES (?, ?, ?)"),
                       (holiday.date, holiday.name, True if holiday.is_national else False))
        conn.commit()
    except Exception:
        conn.close()
        raise HTTPException(status_code=400, detail="Data de feriado já existente ou inválida")
    conn.close()
    return {"message": "Feriado adicionado com sucesso"}

@app.delete("/api/holidays/{holiday_id}")
def delete_holiday(holiday_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(convert_query_for_engine("DELETE FROM holidays WHERE id = ?"), (holiday_id,))
    conn.commit()
    conn.close()
    return {"message": "Feriado removido"}

# --- Rotas de Cálculo & Pré-Visualização ---

@app.get("/api/requests/calculate")
def preview_request_calculation(
    user_id: int,
    start_date: str,
    end_date: str,
    exclude_request_id: Optional[int] = None
):
    business_days = calculate_business_days(start_date, end_date)
    conflicts = detect_conflicts(user_id, start_date, end_date, exclude_request_id)
    balances = get_user_balances(user_id)

    has_enough_balance = (balances.get("remaining_days", 0) >= business_days) if balances else True

    return {
        "business_days": business_days,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "has_enough_balance": has_enough_balance,
        "remaining_after": max(0, balances.get("remaining_days", 0) - business_days) if balances else 0
    }

# --- Rotas de Pedidos de Férias & Fluxo de Cancelamento ---

@app.get("/api/requests")
def list_requests(
    user_id: Optional[int] = None,
    department_id: Optional[int] = None,
    status: Optional[str] = None,
    year: Optional[int] = None
):
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
    SELECT lr.*,
           u.name as user_name, u.email as user_email, u.avatar_color, u.job_title,
           d.name as department_name, d.color as department_color,
           approver.name as approver_name
    FROM leave_requests lr
    JOIN users u ON lr.user_id = u.id
    LEFT JOIN departments d ON u.department_id = d.id
    LEFT JOIN users approver ON lr.approved_by = approver.id
    WHERE 1=1
    """
    params = []

    if user_id:
        query += " AND lr.user_id = ?"
        params.append(user_id)
    if department_id:
        query += " AND u.department_id = ?"
        params.append(department_id)
    if status:
        query += " AND lr.status = ?"
        params.append(status)
    if year:
        query += " AND (lr.start_date LIKE ? OR lr.end_date LIKE ?)"
        params.extend([f"{year}%", f"{year}%"])

    query += " ORDER BY lr.start_date DESC"

    cursor.execute(convert_query_for_engine(query), params)
    requests_list = [dict(row) for row in cursor.fetchall()]
    conn.close()

    for r in requests_list:
        if r["status"] in ("pendente", "cancelamento_pendente"):
            r["conflicts"] = detect_conflicts(r["user_id"], r["start_date"], r["end_date"], exclude_request_id=r["id"])
        else:
            r["conflicts"] = []

    return requests_list

@app.post("/api/requests")
def create_leave_request(req: LeaveRequestCreate):
    if req.start_date > req.end_date:
        raise HTTPException(status_code=400, detail="A data de início deve ser anterior ou igual à data de fim.")

    business_days = calculate_business_days(req.start_date, req.end_date)
    if business_days <= 0:
        raise HTTPException(status_code=400, detail="O intervalo selecionado não contém dias úteis (fins de semana ou feriados).")

    if req.type == 'ferias':
        balances = get_user_balances(req.user_id)
        if balances and balances["remaining_days"] < business_days:
            raise HTTPException(status_code=400, detail=f"Saldo insuficiente ({balances['remaining_days']} dias disponíveis vs {business_days} dias solicitados).")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(convert_query_for_engine("""
    INSERT INTO leave_requests (user_id, type, start_date, end_date, business_days, status, reason)
    VALUES (?, ?, ?, ?, ?, 'pendente', ?)
    """), (req.user_id, req.type, req.start_date, req.end_date, business_days, req.reason))
    conn.commit()
    conn.close()

    return {"business_days": business_days, "message": "Pedido de férias registado com sucesso"}

@app.post("/api/requests/{request_id}/approve")
def approve_request(
    request_id: int,
    action: ApprovalAction,
    active_user_id: Optional[int] = Cookie(default=None)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(convert_query_for_engine("SELECT * FROM leave_requests WHERE id = ?"), (request_id,))
    req = cursor.fetchone()
    if not req:
        conn.close()
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    approver_id = active_user_id if isinstance(active_user_id, int) else None
    cursor.execute(convert_query_for_engine("""
    UPDATE leave_requests
    SET status = 'aprovado', manager_comment = ?, approved_by = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """), (action.manager_comment or "Aprovado", approver_id, request_id))
    conn.commit()
    conn.close()
    return {"message": "Pedido aprovado com sucesso"}

@app.post("/api/requests/{request_id}/reject")
def reject_request(
    request_id: int,
    action: ApprovalAction,
    active_user_id: Optional[int] = Cookie(default=None)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(convert_query_for_engine("SELECT * FROM leave_requests WHERE id = ?"), (request_id,))
    req = cursor.fetchone()
    if not req:
        conn.close()
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    approver_id = active_user_id if isinstance(active_user_id, int) else None
    cursor.execute(convert_query_for_engine("""
    UPDATE leave_requests
    SET status = 'rejeitado', manager_comment = ?, approved_by = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """), (action.manager_comment or "Pedido recusado pela gestão", approver_id, request_id))
    conn.commit()
    conn.close()
    return {"message": "Pedido rejeitado com sucesso"}

# --- FLUXO DE PEDIDO E APROVAÇÃO DE CANCELAMENTO ---

@app.post("/api/requests/{request_id}/cancel")
def request_or_perform_cancel(
    request_id: int,
    action: CancelRequestAction = Body(default=CancelRequestAction())
):
    """
    Colaborador cancela o pedido:
    - Se estiver 'pendente': cancela imediatamente.
    - Se estiver 'aprovado': envia pedido de cancelamento para o Gestor aprovar ('cancelamento_pendente').
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(convert_query_for_engine("SELECT * FROM leave_requests WHERE id = ?"), (request_id,))
    req = cursor.fetchone()
    if not req:
        conn.close()
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    req_dict = dict(req)
    current_status = req_dict["status"]

    if current_status == "pendente":
        cursor.execute(convert_query_for_engine("""
        UPDATE leave_requests
        SET status = 'cancelado', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """), (request_id,))
        msg = "Pedido de férias cancelado."
    elif current_status == "aprovado":
        reason_note = f"Solicitação de cancelamento: {action.reason}" if action.reason else "Solicitação de cancelamento pelo colaborador"
        cursor.execute(convert_query_for_engine("""
        UPDATE leave_requests
        SET status = 'cancelamento_pendente', manager_comment = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """), (reason_note, request_id))
        msg = "Pedido de cancelamento enviado para aprovação da gestão."
    else:
        conn.close()
        raise HTTPException(status_code=400, detail="Este pedido já se encontra cancelado ou rejeitado.")

    conn.commit()
    conn.close()
    return {"message": msg}

@app.post("/api/requests/{request_id}/approve-cancel")
def approve_cancellation(
    request_id: int,
    action: ApprovalAction,
    active_user_id: Optional[int] = Cookie(default=None)
):
    """Gestor aprova o cancelamento e devolve os dias ao saldo do colaborador."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(convert_query_for_engine("SELECT * FROM leave_requests WHERE id = ?"), (request_id,))
    req = cursor.fetchone()
    if not req:
        conn.close()
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    approver_id = active_user_id if isinstance(active_user_id, int) else None
    cursor.execute(convert_query_for_engine("""
    UPDATE leave_requests
    SET status = 'cancelado', manager_comment = ?, approved_by = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """), (action.manager_comment or "Cancelamento aprovado pela gestão. Dias devolvidos ao saldo.", approver_id, request_id))
    conn.commit()
    conn.close()
    return {"message": "Cancelamento aprovado. Os dias foram devolvidos ao saldo do colaborador."}

@app.post("/api/requests/{request_id}/reject-cancel")
def reject_cancellation(
    request_id: int,
    action: ApprovalAction,
    active_user_id: Optional[int] = Cookie(default=None)
):
    """Gestor rejeita o cancelamento, mantendo o pedido 'aprovado'."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(convert_query_for_engine("SELECT * FROM leave_requests WHERE id = ?"), (request_id,))
    req = cursor.fetchone()
    if not req:
        conn.close()
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    approver_id = active_user_id if isinstance(active_user_id, int) else None
    cursor.execute(convert_query_for_engine("""
    UPDATE leave_requests
    SET status = 'aprovado', manager_comment = ?, approved_by = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """), (action.manager_comment or "Pedido de cancelamento recusado pela gestão.", approver_id, request_id))
    conn.commit()
    conn.close()
    return {"message": "Pedido de cancelamento recusado. As férias mantêm-se aprovadas."}

# --- Calendário & Timeline Feed ---

@app.get("/api/calendar/events")
def get_calendar_events():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT lr.*, u.name as user_name, u.avatar_color, d.name as dept_name, d.color as dept_color
    FROM leave_requests lr
    JOIN users u ON lr.user_id = u.id
    LEFT JOIN departments d ON u.department_id = d.id
    WHERE lr.status IN ('aprovado', 'pendente', 'cancelamento_pendente')
    """)
    leaves = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT * FROM holidays")
    holidays = [dict(row) for row in cursor.fetchall()]
    conn.close()

    events = []

    for l in leaves:
        is_pending = (l["status"] in ('pendente', 'cancelamento_pendente'))
        type_labels = {
            "ferias": "Férias",
            "baixa": "Baixa Médica",
            "parental": "Licença Parental",
            "formacao": "Formação",
            "outro": "Outra Ausência"
        }
        type_label = type_labels.get(l["type"], l["type"])
        status_prefix = "⏳ [Pendente] " if l["status"] == "pendente" else ("⚠️ [A Cancelar] " if l["status"] == "cancelamento_pendente" else "")
        title = f"{status_prefix}{l['user_name']} - {type_label}"

        if is_pending:
            bg_color = "#9CA3AF"
            border_color = "#6B7280"
        elif l["type"] == "ferias":
            bg_color = l.get("dept_color") or "#3B82F6"
            border_color = bg_color
        elif l["type"] == "baixa":
            bg_color = "#EF4444"
            border_color = "#DC2626"
        elif l["type"] == "parental":
            bg_color = "#EC4899"
            border_color = "#DB2777"
        else:
            bg_color = "#8B5CF6"
            border_color = "#7C3AED"

        events.append({
            "id": f"leave-{l['id']}",
            "title": title,
            "start": l["start_date"],
            "end": (parse_date(l["end_date"]) + timedelta(days=1)).strftime("%Y-%m-%d"),
            "backgroundColor": bg_color,
            "borderColor": border_color,
            "extendedProps": {
                "user_id": l["user_id"],
                "user_name": l["user_name"],
                "dept_name": l["dept_name"],
                "type": l["type"],
                "status": l["status"],
                "business_days": l["business_days"],
                "reason": l["reason"]
            }
        })

    for h in holidays:
        events.append({
            "id": f"holiday-{h['id']}",
            "title": f"🎉 {h['name']}",
            "start": h["date"],
            "allDay": True,
            "backgroundColor": "#FEF3C7",
            "borderColor": "#F59E0B",
            "textColor": "#92400E",
            "extendedProps": {
                "is_holiday": True,
                "is_national": bool(h["is_national"])
            }
        })

    return events

# --- Dashboard & Relatórios ---

@app.get("/api/stats")
def get_stats(active_user_id: Optional[int] = Cookie(default=None)):
    user = get_current_user_from_db(active_user_id) if active_user_id else None
    role = user["role"] if user else "colaborador"
    dept_id = user["department_id"] if user else None
    uid = user["id"] if user else 0
    return get_dashboard_stats(uid, role, dept_id)

@app.get("/api/export/csv")
def export_csv():
    content = generate_csv_report()
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mapa_ferias_equipa.csv"}
    )

@app.get("/api/export/ics")
def export_ics():
    content = generate_ical_feed()
    return Response(
        content=content,
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=ferias_equipa.ics"}
    )

@app.get("/", response_class=HTMLResponse)
def index_view(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

def parse_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()
