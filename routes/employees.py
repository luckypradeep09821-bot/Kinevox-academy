"""
routes/employees.py
====================
Employee management endpoints:

  GET    /api/employees               — list all employees
  POST   /api/employees               — create employee
  GET    /api/employees/<id>          — get single employee
  PUT    /api/employees/<id>          — update employee
  DELETE /api/employees/<id>          — delete employee

  GET    /api/employees/<id>/attendance          — monthly attendance summary
  POST   /api/employees/<id>/attendance          — upsert monthly summary
  GET    /api/employees/<id>/attendance/log      — daily log
  POST   /api/employees/<id>/attendance/log      — add/update a daily log entry
  GET    /api/employees/<id>/schedule            — schedule info
  PUT    /api/employees/<id>/schedule            — update schedule
  GET    /api/employees/<id>/salary-history      — past salary slips
"""

import json
from flask import Blueprint, request

from db.database import get_db
from middleware.auth import require_auth
from utils.helpers import (
    ok, err, created, not_found, server_error,
    row_to_dict, rows_to_list, next_id, require_fields
)
from utils.email_notify import notify_new_record

emp_bp = Blueprint("employees", __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _emp_with_attendance(conn, emp_row: dict) -> dict:
    """Enrich an employee dict with current-month attendance."""
    from datetime import date
    month = date.today().strftime("%Y-%m")
    att = conn.execute(
        "SELECT * FROM attendance WHERE emp_id=? AND month=?",
        (emp_row["id"], month),
    ).fetchone()
    emp_row["attendance"] = (
        {"present": att["present"], "absent": att["absent"], "late": att["late"]}
        if att
        else {"present": 0, "absent": 0, "late": 0}
    )
    # Deserialise courses JSON
    try:
        emp_row["courses"] = json.loads(emp_row.get("courses") or "[]")
    except Exception:
        emp_row["courses"] = []
    return emp_row


# ── List / Create ─────────────────────────────────────────────────────────────

@emp_bp.route("", methods=["GET"])
@require_auth
def list_employees():
    """
    GET /api/employees
    Query params: ?search=<text>&status=<active|inactive>&dept=<dept>
    """
    q      = request.args.get("search", "").lower()
    status = request.args.get("status", "")
    dept   = request.args.get("dept", "")

    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM employees ORDER BY name").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if q and not any(
                q in (d.get(f) or "").lower()
                for f in ("name", "role", "id", "dept", "email")
            ):
                continue
            if status and d.get("status") != status:
                continue
            if dept and d.get("dept") != dept:
                continue
            result.append(_emp_with_attendance(conn, d))
        return ok(result)
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


@emp_bp.route("", methods=["POST"])
@require_auth
def create_employee():
    """POST /api/employees"""
    body = request.get_json(silent=True) or {}
    error = require_fields(body, ["name"])
    if error:
        return err(error)

    conn = get_db()
    try:
        existing_ids = [r["id"] for r in conn.execute("SELECT id FROM employees").fetchall()]
        emp_id = body.get("id") or next_id("EMP", existing_ids)

        if conn.execute("SELECT 1 FROM employees WHERE id=?", (emp_id,)).fetchone():
            return err(f"Employee ID '{emp_id}' already exists")

        courses_json = json.dumps(body.get("courses") or [])

        conn.execute(
            """INSERT INTO employees
               (id,name,role,dept,email,phone,doj,salary,bonus,credits,
                schedule,status,courses)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                emp_id,
                body["name"],
                body.get("role", ""),
                body.get("dept", "Programming"),
                body.get("email", ""),
                body.get("phone", ""),
                body.get("doj", ""),
                int(body.get("salary") or 0),
                int(body.get("bonus") or 0),
                int(body.get("credits") or 0),
                body.get("schedule", ""),
                body.get("status", "active"),
                courses_json,
            ),
        )
        conn.commit()

        new_emp = dict(conn.execute(
            "SELECT * FROM employees WHERE id=?", (emp_id,)
        ).fetchone())
        enriched = _emp_with_attendance(conn, new_emp)
        notify_new_record("employee", enriched)
        return created(enriched, "Employee created")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Single employee ───────────────────────────────────────────────────────────

@emp_bp.route("/<emp_id>", methods=["GET"])
@require_auth
def get_employee(emp_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        if not row:
            return not_found("Employee")
        return ok(_emp_with_attendance(conn, dict(row)))
    finally:
        conn.close()


@emp_bp.route("/<emp_id>", methods=["PUT"])
@require_auth
def update_employee(emp_id):
    conn = get_db()
    try:
        existing = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        if not existing:
            return not_found("Employee")

        body = request.get_json(silent=True) or {}
        courses_json = json.dumps(body.get("courses") or [])

        conn.execute(
            """UPDATE employees SET
               name=?, role=?, dept=?, email=?, phone=?, doj=?, salary=?,
               bonus=?, credits=?, schedule=?, status=?, courses=?,
               updated_at=datetime('now')
               WHERE id=?""",
            (
                body.get("name", existing["name"]),
                body.get("role", existing["role"]),
                body.get("dept", existing["dept"]),
                body.get("email", existing["email"]),
                body.get("phone", existing["phone"]),
                body.get("doj", existing["doj"]),
                int(body.get("salary") or existing["salary"] or 0),
                int(body.get("bonus") or existing["bonus"] or 0),
                int(body.get("credits") or existing["credits"] or 0),
                body.get("schedule", existing["schedule"]),
                body.get("status", existing["status"]),
                courses_json,
                emp_id,
            ),
        )
        conn.commit()

        updated = dict(conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone())
        return ok(_emp_with_attendance(conn, updated), "Employee updated")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


@emp_bp.route("/<emp_id>", methods=["DELETE"])
@require_auth
def delete_employee(emp_id):
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM employees WHERE id=?", (emp_id,)).fetchone():
            return not_found("Employee")
        conn.execute("DELETE FROM employees WHERE id=?", (emp_id,))
        conn.commit()
        return ok(message="Employee deleted")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Attendance summary ────────────────────────────────────────────────────────

@emp_bp.route("/<emp_id>/attendance", methods=["GET"])
@require_auth
def get_attendance(emp_id):
    """
    GET /api/employees/<id>/attendance?month=2024-05
    Returns monthly summary for one or all months.
    """
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM employees WHERE id=?", (emp_id,)).fetchone():
            return not_found("Employee")

        month = request.args.get("month")
        if month:
            row = conn.execute(
                "SELECT * FROM attendance WHERE emp_id=? AND month=?",
                (emp_id, month),
            ).fetchone()
            return ok(row_to_dict(row) or {"emp_id": emp_id, "month": month, "present": 0, "absent": 0, "late": 0})
        else:
            rows = conn.execute(
                "SELECT * FROM attendance WHERE emp_id=? ORDER BY month DESC",
                (emp_id,),
            ).fetchall()
            return ok(rows_to_list(rows))
    finally:
        conn.close()


@emp_bp.route("/<emp_id>/attendance", methods=["POST"])
@require_auth
def upsert_attendance(emp_id):
    """
    POST /api/employees/<id>/attendance
    Body: { "month": "2024-05", "present": 22, "absent": 2, "late": 1 }
    """
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM employees WHERE id=?", (emp_id,)).fetchone():
            return not_found("Employee")

        body  = request.get_json(silent=True) or {}
        month = body.get("month")
        if not month:
            return err("'month' field is required (YYYY-MM)")

        conn.execute(
            """INSERT INTO attendance (emp_id,month,present,absent,late)
               VALUES (?,?,?,?,?)
               ON CONFLICT(emp_id,month) DO UPDATE SET
                 present=excluded.present,
                 absent=excluded.absent,
                 late=excluded.late""",
            (
                emp_id, month,
                int(body.get("present") or 0),
                int(body.get("absent") or 0),
                int(body.get("late") or 0),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM attendance WHERE emp_id=? AND month=?", (emp_id, month)
        ).fetchone()
        return ok(row_to_dict(row), "Attendance updated")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Daily attendance log ──────────────────────────────────────────────────────

@emp_bp.route("/<emp_id>/attendance/log", methods=["GET"])
@require_auth
def get_attendance_log(emp_id):
    """
    GET /api/employees/<id>/attendance/log?month=2024-05
    Returns daily records. If no month param, returns last 30 entries.
    """
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM employees WHERE id=?", (emp_id,)).fetchone():
            return not_found("Employee")

        month = request.args.get("month")
        if month:
            rows = conn.execute(
                """SELECT * FROM attendance_log
                   WHERE emp_id=? AND strftime('%Y-%m',date)=?
                   ORDER BY date""",
                (emp_id, month),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM attendance_log WHERE emp_id=? ORDER BY date DESC LIMIT 30",
                (emp_id,),
            ).fetchall()
        return ok(rows_to_list(rows))
    finally:
        conn.close()


@emp_bp.route("/<emp_id>/attendance/log", methods=["POST"])
@require_auth
def log_attendance(emp_id):
    """
    POST /api/employees/<id>/attendance/log
    Body: { "date": "2024-05-20", "status": "present", "note": "..." }
    Status values: present | absent | late | off
    """
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM employees WHERE id=?", (emp_id,)).fetchone():
            return not_found("Employee")

        body   = request.get_json(silent=True) or {}
        date   = body.get("date")
        status = body.get("status", "present")

        if not date:
            return err("'date' field is required (YYYY-MM-DD)")
        if status not in ("present", "absent", "late", "off"):
            return err("status must be one of: present, absent, late, off")

        conn.execute(
            """INSERT INTO attendance_log (emp_id,date,status,note)
               VALUES (?,?,?,?)
               ON CONFLICT(emp_id,date) DO UPDATE SET
                 status=excluded.status, note=excluded.note""",
            (emp_id, date, status, body.get("note", "")),
        )

        # Auto-update monthly summary
        month = date[:7]
        conn.execute(
            """INSERT INTO attendance (emp_id,month,present,absent,late) VALUES (?,?,0,0,0)
               ON CONFLICT(emp_id,month) DO NOTHING""",
            (emp_id, month),
        )
        for col, val in [("present", "present"), ("absent", "absent"), ("late", "late")]:
            conn.execute(
                f"""UPDATE attendance SET {col}=(
                    SELECT COUNT(*) FROM attendance_log
                    WHERE emp_id=? AND strftime('%Y-%m',date)=? AND status=?
                ) WHERE emp_id=? AND month=?""",
                (emp_id, month, val, emp_id, month),
            )

        conn.commit()
        return ok(message=f"Attendance logged: {status} on {date}")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Schedule ──────────────────────────────────────────────────────────────────

@emp_bp.route("/<emp_id>/schedule", methods=["GET"])
@require_auth
def get_schedule(emp_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, name, schedule FROM employees WHERE id=?", (emp_id,)
        ).fetchone()
        if not row:
            return not_found("Employee")
        return ok({"emp_id": row["id"], "name": row["name"], "schedule": row["schedule"]})
    finally:
        conn.close()


@emp_bp.route("/<emp_id>/schedule", methods=["PUT"])
@require_auth
def update_schedule(emp_id):
    """
    PUT /api/employees/<id>/schedule
    Body: { "schedule": "Mon-Fri 9AM-5PM" }
    """
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM employees WHERE id=?", (emp_id,)).fetchone():
            return not_found("Employee")

        body = request.get_json(silent=True) or {}
        schedule = body.get("schedule", "")
        conn.execute(
            "UPDATE employees SET schedule=?, updated_at=datetime('now') WHERE id=?",
            (schedule, emp_id),
        )
        conn.commit()
        return ok({"schedule": schedule}, "Schedule updated")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Salary history ────────────────────────────────────────────────────────────

@emp_bp.route("/<emp_id>/salary-history", methods=["GET"])
@require_auth
def salary_history(emp_id):
    """GET /api/employees/<id>/salary-history"""
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM employees WHERE id=?", (emp_id,)).fetchone():
            return not_found("Employee")

        rows = conn.execute(
            """SELECT * FROM salary_slips WHERE emp_id=?
               ORDER BY year DESC, month DESC""",
            (emp_id,),
        ).fetchall()
        return ok(rows_to_list(rows))
    finally:
        conn.close()
