import os
import sqlite3
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ferias.db")

IS_POSTGRES = bool(DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")))

if IS_POSTGRES and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

def get_db_connection():
    if IS_POSTGRES:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def convert_query_for_engine(query: str) -> str:
    if IS_POSTGRES:
        return query.replace("?", "%s")
    return query

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    if IS_POSTGRES:
        # PostgreSQL Schema
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            color VARCHAR(50) DEFAULT '#3B82F6',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password VARCHAR(255) DEFAULT '1234',
            role VARCHAR(50) NOT NULL,
            department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
            total_vacation_days INTEGER DEFAULT 22,
            avatar_color VARCHAR(50) DEFAULT '#3B82F6',
            job_title VARCHAR(255),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS leave_requests (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type VARCHAR(50) NOT NULL,
            start_date VARCHAR(20) NOT NULL,
            end_date VARCHAR(20) NOT NULL,
            business_days INTEGER NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'pendente',
            reason TEXT,
            manager_comment TEXT,
            approved_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS holidays (
            id SERIAL PRIMARY KEY,
            date VARCHAR(20) UNIQUE NOT NULL,
            name VARCHAR(255) NOT NULL,
            is_national BOOLEAN DEFAULT TRUE
        );
        """)
    else:
        # SQLite Schema
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            color TEXT DEFAULT '#3B82F6',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT DEFAULT '1234',
            role TEXT NOT NULL,
            department_id INTEGER,
            total_vacation_days INTEGER DEFAULT 22,
            avatar_color TEXT DEFAULT '#3B82F6',
            job_title TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (department_id) REFERENCES departments(id)
        )
        """)

        cursor.execute("PRAGMA table_info(users)")
        cols = [row["name"] for row in cursor.fetchall()]
        if "password" not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN password TEXT DEFAULT '1234'")

        # Criar ou migrar leave_requests sem restrição rígida de CHECK
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS leave_requests_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            business_days INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pendente',
            reason TEXT,
            manager_comment TEXT,
            approved_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (approved_by) REFERENCES users(id)
        )
        """)

        # Migrar dados se leave_requests existir
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leave_requests'")
        if cursor.fetchone():
            cursor.execute("INSERT OR IGNORE INTO leave_requests_new SELECT * FROM leave_requests")
            cursor.execute("DROP TABLE leave_requests")
        cursor.execute("ALTER TABLE leave_requests_new RENAME TO leave_requests")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS holidays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            is_national BOOLEAN DEFAULT 1
        )
        """)

    conn.commit()

    cursor.execute("SELECT COUNT(*) as count FROM users")
    row = cursor.fetchone()
    count = row["count"] if isinstance(row, dict) or hasattr(row, 'keys') else row[0]
    
    if count == 0:
        seed_data(cursor, conn)

    conn.close()

def seed_data(cursor, conn):
    depts = [
        ("Tecnologia & Desenvolvimento", "#3B82F6"),
        ("Recursos Humanos", "#EC4899"),
        ("Vendas & Marketing", "#F59E0B"),
        ("Financeiro & Operações", "#10B981")
    ]
    department_ids = {}
    for name, color in depts:
        cursor.execute(convert_query_for_engine("SELECT id FROM departments WHERE name = ?"), (name,))
        existing = cursor.fetchone()
        if existing:
            department_ids[name] = existing["id"]
        elif IS_POSTGRES:
            cursor.execute(
                "INSERT INTO departments (name, color) VALUES (%s, %s) RETURNING id",
                (name, color)
            )
            department_ids[name] = cursor.fetchone()["id"]
        else:
            cursor.execute("INSERT INTO departments (name, color) VALUES (?, ?)", (name, color))
            department_ids[name] = cursor.lastrowid

    users = [
        ("Sofia Ramos", "sofia.rh@empresa.pt", "1234", "admin", "Recursos Humanos", 22, "#EC4899", "Diretora de Recursos Humanos"),
        ("Carlos Mendes", "carlos.mendes@empresa.pt", "1234", "gestor", "Tecnologia & Desenvolvimento", 22, "#3B82F6", "Lead Developer / Gestor TI"),
        ("Ana Silva", "ana.silva@empresa.pt", "1234", "colaborador", "Tecnologia & Desenvolvimento", 22, "#6366F1", "Engenheira de Software Frontend"),
        ("João Santos", "joao.santos@empresa.pt", "1234", "colaborador", "Tecnologia & Desenvolvimento", 22, "#14B8A6", "Engenheiro de Software Backend"),
        ("Marta Ferreira", "marta.ferreira@empresa.pt", "1234", "gestor", "Vendas & Marketing", 22, "#F59E0B", "Gestora de Marketing"),
        ("Pedro Oliveira", "pedro.oliveira@empresa.pt", "1234", "colaborador", "Vendas & Marketing", 22, "#8B5CF6", "Designer de Produto"),
        ("Inês Costa", "ines.costa@empresa.pt", "1234", "colaborador", "Financeiro & Operações", 22, "#10B981", "Analista Financeira")
    ]
    for u in users:
        name, email, password, role, department_name, days, avatar, title = u
        cursor.execute(convert_query_for_engine("""
        INSERT INTO users (name, email, password, role, department_id, total_vacation_days, avatar_color, job_title)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """), (name, email, password, role, department_ids[department_name], days, avatar, title))

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
    for h in holidays:
        if IS_POSTGRES:
            cursor.execute(convert_query_for_engine("INSERT INTO holidays (date, name, is_national) VALUES (?, ?, ?) ON CONFLICT (date) DO NOTHING"), h)
        else:
            cursor.execute("INSERT OR IGNORE INTO holidays (date, name, is_national) VALUES (?, ?, ?)", h)

    conn.commit()
