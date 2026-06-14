"""
db/database.py
==============
PostgreSQL schema + seed data + a thin compatibility shim so existing
route code (written against sqlite3's `?`-placeholder, `conn.execute(...)`
style) keeps working almost unchanged against Postgres.

Why Postgres? Render's free web service filesystem is ephemeral — any
SQLite file written to disk is lost on every restart/redeploy. A managed
Postgres database (e.g. Neon, Supabase, or Render Postgres) persists data
permanently and is reachable over the network.

Configuration (via .env / Render env vars):
  DATABASE_URL  — full Postgres connection string, e.g.
                  postgresql://user:password@host/dbname?sslmode=require
"""

import os
import re
import json
import hashlib

import psycopg2
import psycopg2.extras


DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Postgres AVG()/NUMERIC results come back as Decimal, which Flask's
# jsonify() cannot serialize. Convert them to float automatically.
psycopg2.extensions.register_type(
    psycopg2.extensions.new_type(
        psycopg2.extensions.DECIMAL.values,
        "DEC2FLOAT",
        lambda value, curs: float(value) if value is not None else None,
    )
)


# ── Compatibility shim ──────────────────────────────────────────────────────
#
# Existing route code calls things like:
#     conn.execute("SELECT * FROM employees WHERE id = ?", (emp_id,))
#     conn.execute("INSERT INTO foo (...) VALUES (:id,:name,...)", record_dict)
#     conn.executescript(SCHEMA)
#     conn.commit() / conn.close()
#
# psycopg2 uses %s / %(name)s placeholders and cursor.execute(), not
# conn.execute(). This wrapper bridges the two so route files don't need
# to be rewritten query-by-query.

_QMARK_RE = re.compile(r"\?")


def _translate_sql(sql: str):
    """Translate SQLite-style placeholders/syntax to PostgreSQL."""
    # ':name' named placeholders -> '%(name)s'
    sql = re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", r"%(\1)s", sql)
    # '?' positional placeholders -> '%s'
    sql = _QMARK_RE.sub("%s", sql)
    # SQLite datetime('now') -> Postgres NOW()
    sql = sql.replace("datetime('now')", "NOW()").replace('datetime("now")', "NOW()")
    # SQLite INSERT OR IGNORE -> Postgres INSERT ... ON CONFLICT DO NOTHING
    if re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", sql, re.IGNORECASE):
        sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql, flags=re.IGNORECASE)
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    # strftime('%Y-%m', date) -> to_char(date::date, 'YYYY-MM')
    sql = re.sub(
        r"strftime\(\s*'%Y-%m'\s*,\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\)",
        r"to_char(\1::date, 'YYYY-MM')",
        sql,
    )
    return sql


class _Row(dict):
    """A dict that also supports positional integer access (row[0]),
    mimicking sqlite3.Row's dual dict/tuple-like behavior."""

    def __init__(self, real_dict_row):
        super().__init__(real_dict_row)
        self._values = list(real_dict_row.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class _Cursor:
    """Wraps a psycopg2 RealDictCursor to mimic sqlite3 cursor's fetch API."""

    def __init__(self, cursor):
        self._cur = cursor

    def fetchone(self):
        row = self._cur.fetchone()
        return _Row(row) if row is not None else None

    def fetchall(self):
        return [_Row(r) for r in self._cur.fetchall()]

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        # Not directly supported by psycopg2; routes in this app don't rely
        # on it (IDs are app-generated strings like EMP004).
        return None


class Connection:
    """Wraps a psycopg2 connection to mimic the sqlite3.Connection API
    used throughout the route files (conn.execute / executescript /
    commit / close), with dict-like rows via RealDictCursor."""

    def __init__(self, pg_conn):
        self._conn = pg_conn

    def execute(self, sql, params=None):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        translated = _translate_sql(sql)
        if params is None:
            cur.execute(translated)
        else:
            cur.execute(translated, params)
        return _Cursor(cur)

    def executemany(self, sql, seq_of_params):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        translated = _translate_sql(sql)
        cur.executemany(translated, seq_of_params)
        return _Cursor(cur)

    def executescript(self, script):
        """Run a multi-statement SQL script (used for schema setup)."""
        cur = self._conn.cursor()
        cur.execute(script)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_db():
    """Return a database connection wrapped for sqlite3-style usage."""
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it as an environment variable "
            "(see .env.example) — e.g. a free Postgres connection string "
            "from Neon or Supabase."
        )
    # Most managed Postgres providers (Neon, Supabase, Render) require SSL.
    # Local/dev databases (localhost) typically don't support it.
    connect_kwargs = {}
    if "sslmode" not in DATABASE_URL and "localhost" not in DATABASE_URL and "127.0.0.1" not in DATABASE_URL:
        connect_kwargs["sslmode"] = "require"
    pg_conn = psycopg2.connect(DATABASE_URL, **connect_kwargs)
    return Connection(pg_conn)


def _hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


# ── Schema (PostgreSQL) ─────────────────────────────────────────────────────

SCHEMA = """
-- Users (admin accounts)
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    TEXT    UNIQUE NOT NULL,
    password    TEXT    NOT NULL,
    role        TEXT    NOT NULL DEFAULT 'admin',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Employees
CREATE TABLE IF NOT EXISTS employees (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    role        TEXT,
    dept        TEXT,
    email       TEXT,
    phone       TEXT,
    doj         TEXT,
    salary      INTEGER DEFAULT 0,
    bonus       INTEGER DEFAULT 0,
    credits     INTEGER DEFAULT 0,
    schedule    TEXT,
    status      TEXT    DEFAULT 'active',
    photo       TEXT,
    sign        TEXT,
    id_doc      TEXT,
    resume      TEXT,
    courses     TEXT    DEFAULT '[]',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Employee Attendance (monthly records)
CREATE TABLE IF NOT EXISTS attendance (
    id          SERIAL PRIMARY KEY,
    emp_id      TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    month       TEXT NOT NULL,   -- e.g. "2024-05"
    present     INTEGER DEFAULT 0,
    absent      INTEGER DEFAULT 0,
    late        INTEGER DEFAULT 0,
    UNIQUE(emp_id, month)
);

-- Attendance daily log
CREATE TABLE IF NOT EXISTS attendance_log (
    id          SERIAL PRIMARY KEY,
    emp_id      TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    date        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'present',  -- present | absent | late | off
    note        TEXT,
    UNIQUE(emp_id, date)
);

-- Courses
CREATE TABLE IF NOT EXISTS courses (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT,
    duration    TEXT,
    fee         INTEGER DEFAULT 0,
    seats       INTEGER DEFAULT 0,
    enrolled    INTEGER DEFAULT 0,
    assigned_to TEXT REFERENCES employees(id) ON DELETE SET NULL,
    description TEXT,
    status      TEXT DEFAULT 'active',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Students
CREATE TABLE IF NOT EXISTS students (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT,
    phone       TEXT,
    dob         TEXT,
    institution TEXT,
    course      TEXT,
    assigned_to TEXT REFERENCES employees(id) ON DELETE SET NULL,
    trainer     TEXT,
    enroll_date TEXT,
    progress    INTEGER DEFAULT 0,
    percentage  INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'active',
    completed   INTEGER DEFAULT 0,
    photo       TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Certificates (issued records)
CREATE TABLE IF NOT EXISTS certificates (
    id          SERIAL PRIMARY KEY,
    student_id  TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    cert_no     TEXT UNIQUE NOT NULL,
    issued_on   TIMESTAMP NOT NULL DEFAULT NOW(),
    course      TEXT NOT NULL
);

-- Salary slip records (history)
CREATE TABLE IF NOT EXISTS salary_slips (
    id          SERIAL PRIMARY KEY,
    emp_id      TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    month       TEXT NOT NULL,
    year        INTEGER NOT NULL,
    basic       INTEGER,
    bonus       INTEGER,
    pf          INTEGER,
    tax         INTEGER,
    gross       INTEGER,
    net         INTEGER,
    generated_on TIMESTAMP NOT NULL DEFAULT NOW()
);
"""

# ── Seed data ────────────────────────────────────────────────────────────────

SEED_USERS = [
    ("admin", "Kinevox123", "admin"),
]

SEED_EMPLOYEES = [
    {
        "id": "EMP001",
        "name": "Arjun Sharma",
        "role": "Senior Developer & Trainer",
        "dept": "Programming",
        "email": "arjun@kinevoxacademy.in",
        "phone": "9876543210",
        "doj": "2023-01-15",
        "salary": 45000,
        "bonus": 5000,
        "credits": 120,
        "schedule": "Mon-Fri 9AM-5PM",
        "status": "active",
        "courses": json.dumps(["Web Development", "React Basics"]),
    },
    {
        "id": "EMP002",
        "name": "Priya Nair",
        "role": "Design & Media Trainer",
        "dept": "Design",
        "email": "priya@kinevoxacademy.in",
        "phone": "9123456789",
        "doj": "2023-03-10",
        "salary": 38000,
        "bonus": 3000,
        "credits": 95,
        "schedule": "Mon-Sat 10AM-6PM",
        "status": "active",
        "courses": json.dumps(["Graphic Design", "Video Editing"]),
    },
    {
        "id": "EMP003",
        "name": "Ravi Menon",
        "role": "Game Dev Instructor",
        "dept": "Programming",
        "email": "ravi@kinevoxacademy.in",
        "phone": "9812345678",
        "doj": "2024-01-01",
        "salary": 42000,
        "bonus": 2000,
        "credits": 60,
        "schedule": "Tue-Sat 11AM-7PM",
        "status": "active",
        "courses": json.dumps(["Game Development"]),
    },
]

SEED_ATTENDANCE = [
    ("EMP001", "2024-05", 22, 2, 1),
    ("EMP002", "2024-05", 20, 3, 2),
    ("EMP003", "2024-05", 18, 1, 3),
]

SEED_COURSES = [
    {
        "id": "CRS001",
        "name": "Web Development",
        "category": "Programming",
        "duration": "3 months",
        "fee": 8000,
        "seats": 15,
        "enrolled": 8,
        "assigned_to": "EMP001",
        "description": "HTML, CSS, JavaScript, React — full-stack fundamentals.",
        "status": "active",
    },
    {
        "id": "CRS002",
        "name": "Graphic Design",
        "category": "Design",
        "duration": "2 months",
        "fee": 6000,
        "seats": 12,
        "enrolled": 6,
        "assigned_to": "EMP002",
        "description": "Photoshop, Illustrator, Canva — visual design mastery.",
        "status": "active",
    },
    {
        "id": "CRS003",
        "name": "Video Editing",
        "category": "Design",
        "duration": "2 months",
        "fee": 7000,
        "seats": 10,
        "enrolled": 4,
        "assigned_to": "EMP002",
        "description": "Premiere Pro, After Effects, DaVinci Resolve.",
        "status": "active",
    },
    {
        "id": "CRS004",
        "name": "React Basics",
        "category": "Programming",
        "duration": "1.5 months",
        "fee": 5500,
        "seats": 12,
        "enrolled": 5,
        "assigned_to": "EMP001",
        "description": "Modern React with hooks, context and state management.",
        "status": "active",
    },
    {
        "id": "CRS005",
        "name": "Game Development",
        "category": "Game Dev",
        "duration": "4 months",
        "fee": 12000,
        "seats": 10,
        "enrolled": 3,
        "assigned_to": "EMP003",
        "description": "Unity 2D/3D game development with C#.",
        "status": "active",
    },
]

SEED_STUDENTS = [
    {
        "id": "STU001",
        "name": "Rahul Verma",
        "email": "rahul@gmail.com",
        "phone": "8765432109",
        "dob": "2005-06-12",
        "institution": "DPS School",
        "course": "Web Development",
        "assigned_to": "EMP001",
        "trainer": "Arjun Sharma",
        "enroll_date": "2024-01-10",
        "progress": 75,
        "percentage": 75,
        "status": "active",
        "completed": 0,
    },
    {
        "id": "STU002",
        "name": "Sneha Patel",
        "email": "sneha@gmail.com",
        "phone": "8654321098",
        "dob": "2004-09-22",
        "institution": "BMS College",
        "course": "Graphic Design",
        "assigned_to": "EMP002",
        "trainer": "Priya Nair",
        "enroll_date": "2024-02-05",
        "progress": 90,
        "percentage": 90,
        "status": "active",
        "completed": 0,
    },
    {
        "id": "STU003",
        "name": "Kiran Kumar",
        "email": "kiran@gmail.com",
        "phone": "9087654321",
        "dob": "2003-12-01",
        "institution": "RV College",
        "course": "Video Editing",
        "assigned_to": "EMP002",
        "trainer": "Priya Nair",
        "enroll_date": "2023-10-01",
        "progress": 100,
        "percentage": 100,
        "status": "completed",
        "completed": 1,
    },
    {
        "id": "STU004",
        "name": "Divya Reddy",
        "email": "divya@gmail.com",
        "phone": "9765432108",
        "dob": "2004-03-15",
        "institution": "Jyoti Nivas",
        "course": "React Basics",
        "assigned_to": "EMP001",
        "trainer": "Arjun Sharma",
        "enroll_date": "2024-03-01",
        "progress": 45,
        "percentage": 45,
        "status": "active",
        "completed": 0,
    },
]


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db(app):
    """Create schema and seed initial data (idempotent)."""
    with app.app_context():
        conn = get_db()
        try:
            # Create tables
            conn.executescript(SCHEMA)
            conn.commit()

            # Users
            for username, password, role in SEED_USERS:
                conn.execute(
                    "INSERT OR IGNORE INTO users (username, password, role) VALUES (?,?,?)",
                    (username, _hash_password(password), role),
                )

            # Employees
            for e in SEED_EMPLOYEES:
                conn.execute(
                    """INSERT OR IGNORE INTO employees
                       (id,name,role,dept,email,phone,doj,salary,bonus,credits,
                        schedule,status,courses)
                       VALUES (:id,:name,:role,:dept,:email,:phone,:doj,:salary,:bonus,
                               :credits,:schedule,:status,:courses)""",
                    e,
                )

            # Attendance summary
            for emp_id, month, present, absent, late in SEED_ATTENDANCE:
                conn.execute(
                    """INSERT OR IGNORE INTO attendance (emp_id,month,present,absent,late)
                       VALUES (?,?,?,?,?)""",
                    (emp_id, month, present, absent, late),
                )

            # Courses
            for c in SEED_COURSES:
                conn.execute(
                    """INSERT OR IGNORE INTO courses
                       (id,name,category,duration,fee,seats,enrolled,
                        assigned_to,description,status)
                       VALUES (:id,:name,:category,:duration,:fee,:seats,:enrolled,
                               :assigned_to,:description,:status)""",
                    c,
                )

            # Students
            for s in SEED_STUDENTS:
                conn.execute(
                    """INSERT OR IGNORE INTO students
                       (id,name,email,phone,dob,institution,course,assigned_to,trainer,
                        enroll_date,progress,percentage,status,completed)
                       VALUES (:id,:name,:email,:phone,:dob,:institution,:course,
                               :assigned_to,:trainer,:enroll_date,:progress,:percentage,
                               :status,:completed)""",
                    s,
                )

            conn.commit()
        finally:
            conn.close()
