import os
import sqlite3
from datetime import datetime, date, timedelta
from typing import Optional, List
from fastapi import FastAPI, Request, Response, HTTPException, Query, Body, Cookie
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .database import get_db_connection, init_db
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

# Garantir existência de pastas
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

app = FastAPI(title="Gestão de Férias da Equipa", description="API e Interface de Gestão de Férias e Ausências")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Inicializar BD
@app.on_event("startup")
def on_startup():
    init_db()

# Modelos Pydantic para validação
class UserLogin(BaseModel):
    email: str
    password: Optional[str] = "1234"

class UserCreate(BaseModel):
    name: str
    email: str
    password: Optional[str] = "1234"
    role: str # 'colaborador', 'gestor', 'admin'
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
    type: str # 'ferias', 'baixa', 'parental', 'formacao', 'outro'
    start_date: str # YYYY-MM-DD
    end_date: str # YYYY-MM-DD
    reason: Optional[str] = ""

class ApprovalAction(BaseModel):
    manager_comment: Optional[str] = ""

# --- Rotas de Autenticação / Sessão Ativa ---

def get_current_user_from_db(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT u.*, d.name as department_name, d.color as department_color
    FROM users u
    LEFT JOIN departments d ON u.department_id = d.id
    WHERE u.id = ? AND u.is_active = 1
    """, (user_id,))
    user = cursor.fetchone()
    conn.close()
    if user:
        return dict(user)
    return None

@app.get("/api/auth/current")
def get_current_user(active_user_id: Optional[int] = Cookie(default=None)):
    if active_user_id:
        user = get_current_user_from_db(active_user_id)
        if user:
            user["balances"] = get_user_balances(user["id"])
            return user
    
    # Fallback para o primeiro utilizador (para facilitar início)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE is_active = 1 LIMIT 1")
    first = cursor.fetchone()
    conn.close()
    if first:
        user = get_current_user_from_db(first["id"])
        if user:
            user["balances"] = get_user_balances(user["id"])
            return user
    return None

@app.post("/api/auth/login")
def login(credentials: UserLogin, response: Response):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ? AND is_active = 1", (credentials.email.strip().lower(),))
    user = cursor.fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Email não encontrado ou colaborador inativo")

    user_dict = dict(user)
    # Validação simples de password (padrão '1234')
    if user_dict.get("password") and user_dict.get("password") != credentials.password:
        raise HTTPException(status_code=401, detail="Palavra-passe incorreta (predefinida: 1234)")

    response.set_cookie(key="active_user_id", value=str(user["id"]), httponly=False, samesite="lax")
    user_dict["balances"] = get_user_balances(user["id"])
    return {"message": f"Bem-vindo(a), {user['name']}", "user": user_dict}

@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(key="active_user_id")
    return {"message": "Sessão terminada com sucesso"}

@app.post("/api/auth/switch")
def switch_user(response: Response, user_id: int = Body(..., embed=True)):
    user = get_current_user_from_db(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    
    response.set_cookie(key="active_user_id", value=str(user_id), httponly=False, samesite="lax")
    user["balances"] = get_user_balances(user_id)
    return {"message": f"Sessão alterada para {user['name']}", "user": user}

# --- Rotas de Gestão de Utilizadores (CRUD Completo de Admin) ---

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
    WHERE u.is_active = 1
    ORDER BY u.name ASC
    """)
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()

    for u in users:
        u["balances"] = get_user_balances(u["id"])

    return users

@app.post("/api/users")
def create_user(user: UserCreate, active_user_id: Optional[int] = Cookie(default=1)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO users (name, email, password, role, department_id, total_vacation_days, job_title, avatar_color)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
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
        new_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Este email já se encontra registado no sistema.")
    conn.close()
    return {"id": new_id, "message": f"Colaborador {user.name} criado com sucesso (Dotação: {user.total_vacation_days or 22} dias)"}

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
        values.append(1 if update.is_active else 0)

    if not fields:
        conn.close()
        return {"message": "Sem alterações"}

    values.append(user_id)
    cursor.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return {"message": "Dados do colaborador atualizados com sucesso"}

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, active_user_id: Optional[int] = Cookie(default=1)):
    """Elimina um colaborador e os seus pedidos de férias."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verificar se utilizador existe
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    target = cursor.fetchone()
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")

    # Eliminar pedidos associados e utilizador
    cursor.execute("DELETE FROM leave_requests WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"message": f"Colaborador {target['name']} eliminado com sucesso"}

# --- Rotas de Departamentos ---

@app.get("/api/departments")
def list_departments():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT d.*, COUNT(u.id) as members_count
    FROM departments d
    LEFT JOIN users u ON u.department_id = d.id AND u.is_active = 1
    GROUP BY d.id
    ORDER BY d.name ASC
    """)
    depts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return depts

@app.post("/api/departments")
def create_department(dept: DepartmentCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO departments (name, color) VALUES (?, ?)", (dept.name, dept.color))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return {"id": new_id, "message": "Departamento criado com sucesso"}

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
        cursor.execute("INSERT INTO holidays (date, name, is_national) VALUES (?, ?, ?)",
                       (holiday.date, holiday.name, 1 if holiday.is_national else 0))
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
    cursor.execute("DELETE FROM holidays WHERE id = ?", (holiday_id,))
    conn.commit()
    conn.close()
    return {"message": "Feriado removido"}

# --- Rotas de Cálculo & Pré-Visualização de Pedidos ---

@app.get("/api/requests/calculate")
def preview_request_calculation(
    user_id: int,
    start_date: str,
    end_date: str,
    exclude_request_id: Optional[int] = None
):
    """Calcula dias úteis e deteta sobreposições/conflitos antes de submeter."""
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

# --- Rotas de Pedidos de Férias (CRUD & Aprovações) ---

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
        query += " AND (strftime('%Y', lr.start_date) = ? OR strftime('%Y', lr.end_date) = ?)"
        params.extend([str(year), str(year)])

    query += " ORDER BY lr.start_date DESC"

    cursor.execute(query, params)
    requests_list = [dict(row) for row in cursor.fetchall()]
    conn.close()

    for r in requests_list:
        if r["status"] == "pendente":
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
    cursor.execute("""
    INSERT INTO leave_requests (user_id, type, start_date, end_date, business_days, status, reason)
    VALUES (?, ?, ?, ?, ?, 'pendente', ?)
    """, (req.user_id, req.type, req.start_date, req.end_date, business_days, req.reason))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()

    return {"id": new_id, "business_days": business_days, "message": "Pedido de férias registado com sucesso"}

@app.post("/api/requests/{request_id}/approve")
def approve_request(
    request_id: int,
    action: ApprovalAction,
    active_user_id: Optional[int] = Cookie(default=1)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leave_requests WHERE id = ?", (request_id,))
    req = cursor.fetchone()
    if not req:
        conn.close()
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    cursor.execute("""
    UPDATE leave_requests
    SET status = 'aprovado', manager_comment = ?, approved_by = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (action.manager_comment, active_user_id, request_id))
    conn.commit()
    conn.close()
    return {"message": "Pedido aprovado com sucesso"}

@app.post("/api/requests/{request_id}/reject")
def reject_request(
    request_id: int,
    action: ApprovalAction,
    active_user_id: Optional[int] = Cookie(default=1)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leave_requests WHERE id = ?", (request_id,))
    req = cursor.fetchone()
    if not req:
        conn.close()
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    cursor.execute("""
    UPDATE leave_requests
    SET status = 'rejeitado', manager_comment = ?, approved_by = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (action.manager_comment or "Pedido recusado pela gestão", active_user_id, request_id))
    conn.commit()
    conn.close()
    return {"message": "Pedido rejeitado com sucesso"}

@app.post("/api/requests/{request_id}/cancel")
def cancel_request(request_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leave_requests WHERE id = ?", (request_id,))
    req = cursor.fetchone()
    if not req:
        conn.close()
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    if req["status"] not in ("pendente", "aprovado"):
        conn.close()
        raise HTTPException(status_code=400, detail="Apenas pedidos pendentes ou aprovados podem ser cancelados")

    cursor.execute("""
    UPDATE leave_requests
    SET status = 'cancelado', updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (request_id,))
    conn.commit()
    conn.close()
    return {"message": "Pedido cancelado com sucesso"}

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
    WHERE lr.status IN ('aprovado', 'pendente')
    """)
    leaves = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT * FROM holidays")
    holidays = [dict(row) for row in cursor.fetchall()]
    conn.close()

    events = []

    for l in leaves:
        is_pending = (l["status"] == "pendente")
        type_labels = {
            "ferias": "Férias",
            "baixa": "Baixa Médica",
            "parental": "Licença Parental",
            "formacao": "Formação",
            "outro": "Outra Ausência"
        }
        type_label = type_labels.get(l["type"], l["type"])
        title = f"{'⏳ [Pendente] ' if is_pending else ''}{l['user_name']} - {type_label}"

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
def get_stats(active_user_id: Optional[int] = Cookie(default=3)):
    user = get_current_user_from_db(active_user_id) if active_user_id else None
    role = user["role"] if user else "colaborador"
    dept_id = user["department_id"] if user else None
    uid = user["id"] if user else 1
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

# --- Frontend HTML ---

@app.get("/", response_class=HTMLResponse)
def index_view(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

def parse_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()
