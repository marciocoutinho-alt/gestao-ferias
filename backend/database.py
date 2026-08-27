import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ferias.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Tabela de Departamentos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS departments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        color TEXT DEFAULT '#3B82F6',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Tabela de Utilizadores (Colaboradores / Gestores / Admins)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT DEFAULT '1234',
        role TEXT NOT NULL CHECK(role IN ('colaborador', 'gestor', 'admin')),
        department_id INTEGER,
        total_vacation_days INTEGER DEFAULT 22,
        avatar_color TEXT DEFAULT '#3B82F6',
        job_title TEXT,
        is_active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (department_id) REFERENCES departments(id)
    )
    """)

    # Migração segura para garantir existência da coluna password
    cursor.execute("PRAGMA table_info(users)")
    columns = [row["name"] for row in cursor.fetchall()]
    if "password" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN password TEXT DEFAULT '1234'")

    # Tabela de Pedidos de Ausência / Férias
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leave_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('ferias', 'baixa', 'parental', 'formacao', 'outro')),
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        business_days INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pendente', 'aprovado', 'rejeitado', 'cancelado')) DEFAULT 'pendente',
        reason TEXT,
        manager_comment TEXT,
        approved_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (approved_by) REFERENCES users(id)
    )
    """)

    # Tabela de Feriados Nacionais e Pontes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS holidays (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        is_national BOOLEAN DEFAULT 1
    )
    """)

    conn.commit()

    # Seed data se estiver vazia
    cursor.execute("SELECT COUNT(*) as count FROM users")
    if cursor.fetchone()['count'] == 0:
        seed_data(cursor, conn)

    conn.close()

def seed_data(cursor, conn):
    # Departamentos
    depts = [
        ("Tecnologia & Desenvolvimento", "#3B82F6"),
        ("Recursos Humanos", "#EC4899"),
        ("Vendas & Marketing", "#F59E0B"),
        ("Financeiro & Operações", "#10B981")
    ]
    cursor.executemany("INSERT INTO departments (name, color) VALUES (?, ?)", depts)

    # Utilizadores com password padrão '1234'
    users = [
        ("Sofia Ramos", "sofia.rh@empresa.pt", "1234", "admin", 2, 22, "#EC4899", "Diretora de Recursos Humanos"),
        ("Carlos Mendes", "carlos.mendes@empresa.pt", "1234", "gestor", 1, 22, "#3B82F6", "Lead Developer / Gestor TI"),
        ("Ana Silva", "ana.silva@empresa.pt", "1234", "colaborador", 1, 22, "#6366F1", "Engenheira de Software Frontend"),
        ("João Santos", "joao.santos@empresa.pt", "1234", "colaborador", 1, 22, "#14B8A6", "Engenheiro de Software Backend"),
        ("Marta Ferreira", "marta.ferreira@empresa.pt", "1234", "gestor", 3, 22, "#F59E0B", "Gestora de Marketing"),
        ("Pedro Oliveira", "pedro.oliveira@empresa.pt", "1234", "colaborador", 3, 22, "#8B5CF6", "Designer de Produto"),
        ("Inês Costa", "ines.costa@empresa.pt", "1234", "colaborador", 4, 22, "#10B981", "Analista Financeira")
    ]
    cursor.executemany("""
    INSERT INTO users (name, email, password, role, department_id, total_vacation_days, avatar_color, job_title)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, users)

    # Feriados de Portugal (2026 e genéricos)
    holidays = [
        ("2026-01-01", "Ano Novo", 1),
        ("2026-02-17", "Carnaval (Terça-feira)", 0),
        ("2026-04-03", "Sexta-feira Santa", 1),
        ("2026-04-05", "Páscoa", 1),
        ("2026-04-25", "Dia da Liberdade", 1),
        ("2026-05-01", "Dia do Trabalhador", 1),
        ("2026-06-04", "Corpo de Deus", 1),
        ("2026-06-10", "Dia de Portugal", 1),
        ("2026-08-15", "Assunção de Nossa Senhora", 1),
        ("2026-10-05", "Implantação da República", 1),
        ("2026-11-01", "Dia de Todos os Santos", 1),
        ("2026-12-01", "Restauração da Independência", 1),
        ("2026-12-08", "Dia da Imaculada Conceição", 1),
        ("2026-12-25", "Natal", 1),
    ]
    cursor.executemany("INSERT OR IGNORE INTO holidays (date, name, is_national) VALUES (?, ?, ?)", holidays)

    # Exemplos de pedidos de férias
    sample_requests = [
        (3, "ferias", "2026-07-13", "2026-07-24", 10, "aprovado", "Férias de Verão", "Aprovado. Bom descanso!", 2),
        (4, "ferias", "2026-07-20", "2026-07-31", 10, "pendente", "Férias com a família", None, None),
        (3, "ferias", "2026-12-21", "2026-12-31", 8, "pendente", "Época Festiva de Natal", None, None),
        (6, "ferias", "2026-08-03", "2026-08-14", 10, "aprovado", "Férias de Agosto", "Aprovado!", 5),
        (7, "baixa", "2026-02-02", "2026-02-04", 3, "aprovado", "Consulta e recuperação", "Registado.", 1)
    ]
    cursor.executemany("""
    INSERT INTO leave_requests (user_id, type, start_date, end_date, business_days, status, reason, manager_comment, approved_by)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sample_requests)

    conn.commit()
