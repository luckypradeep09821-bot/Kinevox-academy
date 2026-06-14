"""
routes/payroll.py
==================
Payroll & ID card endpoints:

  GET  /api/payroll/summary              — all employees with payroll data
  GET  /api/payroll/<emp_id>/slip        — calculate salary slip for current month
  POST /api/payroll/<emp_id>/slip        — generate & persist salary slip record
  GET  /api/payroll/<emp_id>/id-card     — employee ID card data
  GET  /api/payroll/slips                — all issued salary slips (with filters)
"""

from flask import Blueprint, request
from datetime import date

from db.database import get_db
from middleware.auth import require_auth
from utils.helpers import (
    ok, err, created, not_found, server_error,
    row_to_dict, rows_to_list, calc_payroll
)
import json

pay_bp = Blueprint("payroll", __name__)

MONTHS = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
]


# ── Payroll summary (all employees) ──────────────────────────────────────────

@pay_bp.route("/summary", methods=["GET"])
@require_auth
def payroll_summary():
    """
    GET /api/payroll/summary
    Returns all employees with calculated payroll breakdown.
    """
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM employees ORDER BY name").fetchall()
        result = []
        for r in rows:
            e   = dict(r)
            pay = calc_payroll(e.get("salary") or 0, e.get("bonus") or 0)
            result.append({
                "id":     e["id"],
                "name":   e["name"],
                "role":   e["role"],
                "dept":   e["dept"],
                "status": e["status"],
                **pay,
            })
        return ok(result)
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Salary slip (calculate) ───────────────────────────────────────────────────

@pay_bp.route("/<emp_id>/slip", methods=["GET"])
@require_auth
def get_salary_slip(emp_id):
    """
    GET /api/payroll/<emp_id>/slip?month=5&year=2026
    Returns calculated salary slip data (not persisted).
    """
    conn = get_db()
    try:
        emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        if not emp:
            return not_found("Employee")

        today = date.today()
        month = int(request.args.get("month", today.month))
        year  = int(request.args.get("year",  today.year))

        # Attendance for the given month
        month_str = f"{year}-{month:02d}"
        att = conn.execute(
            "SELECT * FROM attendance WHERE emp_id=? AND month=?",
            (emp_id, month_str),
        ).fetchone()
        working_days  = att["present"] if att else 22
        total_days    = 25

        pay = calc_payroll(emp["salary"] or 0, emp["bonus"] or 0)

        slip = {
            "emp_id":       emp["id"],
            "emp_name":     emp["name"],
            "role":         emp["role"],
            "dept":         emp["dept"],
            "doj":          emp["doj"],
            "email":        emp["email"],
            "month":        MONTHS[month - 1],
            "month_num":    month,
            "year":         year,
            "month_label":  f"{MONTHS[month - 1]} {year}",
            "working_days": working_days,
            "total_days":   total_days,
            **pay,
        }
        return ok(slip)
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Generate & persist salary slip ───────────────────────────────────────────

@pay_bp.route("/<emp_id>/slip", methods=["POST"])
@require_auth
def generate_salary_slip(emp_id):
    """
    POST /api/payroll/<emp_id>/slip
    Body: { "month": 5, "year": 2026 }
    Persists a salary slip record and returns it.
    """
    conn = get_db()
    try:
        emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        if not emp:
            return not_found("Employee")

        body  = request.get_json(silent=True) or {}
        today = date.today()
        month = int(body.get("month", today.month))
        year  = int(body.get("year",  today.year))

        pay = calc_payroll(emp["salary"] or 0, emp["bonus"] or 0)

        conn.execute(
            """INSERT INTO salary_slips
               (emp_id,month,year,basic,bonus,pf,tax,gross,net)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                emp_id,
                MONTHS[month - 1],
                year,
                pay["basic"],
                pay["bonus"],
                pay["pf"],
                pay["tax"],
                pay["gross"],
                pay["net"],
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM salary_slips WHERE emp_id=? ORDER BY id DESC LIMIT 1",
            (emp_id,),
        ).fetchone()
        return created(row_to_dict(row), "Salary slip generated")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── ID card data ──────────────────────────────────────────────────────────────

@pay_bp.route("/<emp_id>/id-card", methods=["GET"])
@require_auth
def get_id_card(emp_id):
    """
    GET /api/payroll/<emp_id>/id-card
    Returns all data needed to render the employee ID card.
    """
    conn = get_db()
    try:
        emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        if not emp:
            return not_found("Employee")

        e = dict(emp)

        # Courses
        try:
            courses = json.loads(e.get("courses") or "[]")
        except Exception:
            courses = []

        card_data = {
            "id":         e["id"],
            "name":       e["name"],
            "role":       e["role"],
            "dept":       e["dept"],
            "email":      e["email"],
            "phone":      e["phone"],
            "doj":        e["doj"],
            "status":     e["status"],
            "schedule":   e["schedule"],
            "photo":      e.get("photo"),
            "courses":    courses,
            "institute":  "Kinevox Academy Institute",
            "campus":     "Chennai",
            "qr_data":    f"TSI-EMP|{e['id']}|{e['name']}|{e['role']}|{e['dept']}",
        }
        return ok(card_data)
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── All salary slips ──────────────────────────────────────────────────────────

@pay_bp.route("/slips", methods=["GET"])
@require_auth
def all_slips():
    """
    GET /api/payroll/slips?emp_id=EMP001&year=2026&month=May
    """
    conn = get_db()
    try:
        emp_id = request.args.get("emp_id", "")
        year   = request.args.get("year", "")
        month  = request.args.get("month", "")

        query  = "SELECT ss.*, e.name as emp_name, e.role FROM salary_slips ss JOIN employees e ON ss.emp_id=e.id WHERE 1=1"
        params = []

        if emp_id:
            query  += " AND ss.emp_id=?"
            params.append(emp_id)
        if year:
            query  += " AND ss.year=?"
            params.append(int(year))
        if month:
            query  += " AND ss.month=?"
            params.append(month)

        query += " ORDER BY ss.year DESC, ss.generated_on DESC"
        rows   = conn.execute(query, params).fetchall()
        return ok(rows_to_list(rows))
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()
