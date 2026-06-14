"""
routes/reports.py
==================
Analytics & reporting endpoints:

  GET /api/reports/dashboard     — high-level stats (counts + revenue)
  GET /api/reports/revenue       — revenue breakdown by course
  GET /api/reports/students      — student distribution by course/status
  GET /api/reports/attendance    — attendance summary across all employees
  GET /api/reports/courses       — course performance metrics
  GET /api/reports/employees     — employee overview stats
  GET /api/reports/full          — everything combined in one call
"""

from flask import Blueprint, request
from datetime import date

from db.database import get_db
from middleware.auth import require_auth
from utils.helpers import ok, server_error, rows_to_list

rep_bp = Blueprint("reports", __name__)


# ── Dashboard summary ─────────────────────────────────────────────────────────

@rep_bp.route("/dashboard", methods=["GET"])
@require_auth
def dashboard():
    """
    GET /api/reports/dashboard
    Returns top-level KPIs matching the frontend dashboard cards.
    """
    conn = get_db()
    try:
        emp_count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        stu_count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        crs_count = conn.execute(
            "SELECT COUNT(*) FROM courses WHERE status='active'"
        ).fetchone()[0]

        # Revenue = sum of fee * enrolled across all courses
        rev_row = conn.execute(
            "SELECT SUM(fee * enrolled) as total FROM courses"
        ).fetchone()
        monthly_revenue = rev_row["total"] or 0

        # Recent employees (last 3)
        recent_emps = rows_to_list(
            conn.execute(
                "SELECT id,name,role,status,dept FROM employees ORDER BY created_at DESC LIMIT 3"
            ).fetchall()
        )

        # Recent students (last 4)
        recent_stus = rows_to_list(
            conn.execute(
                "SELECT id,name,course,progress,percentage,status FROM students ORDER BY created_at DESC LIMIT 4"
            ).fetchall()
        )

        # Course enrollment bars (top 5)
        course_bars = rows_to_list(
            conn.execute(
                "SELECT id,name,enrolled,seats FROM courses ORDER BY enrolled DESC LIMIT 5"
            ).fetchall()
        )

        return ok({
            "emp_count":        emp_count,
            "stu_count":        stu_count,
            "crs_count":        crs_count,
            "monthly_revenue":  monthly_revenue,
            "rev_label":        f"{monthly_revenue / 1000:.0f}K",
            "recent_employees": recent_emps,
            "recent_students":  recent_stus,
            "course_bars":      course_bars,
        })
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Revenue by course ──────────────────────────────────────────────────────────

@rep_bp.route("/revenue", methods=["GET"])
@require_auth
def revenue():
    """
    GET /api/reports/revenue
    Returns revenue contribution per course.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT name, category, fee, enrolled, seats,
                      (fee * enrolled) as revenue
               FROM courses
               ORDER BY revenue DESC"""
        ).fetchall()

        data = rows_to_list(rows)
        total = sum(r["revenue"] or 0 for r in data)

        for r in data:
            r["pct"] = round((r["revenue"] / total * 100) if total else 0, 1)

        return ok({"courses": data, "total_revenue": total})
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Student distribution ───────────────────────────────────────────────────────

@rep_bp.route("/students", methods=["GET"])
@require_auth
def student_distribution():
    """
    GET /api/reports/students
    Student counts by course, by status, and progress buckets.
    """
    conn = get_db()
    try:
        # By course
        by_course = rows_to_list(conn.execute(
            "SELECT course, COUNT(*) as count FROM students GROUP BY course ORDER BY count DESC"
        ).fetchall())

        # By status
        by_status = rows_to_list(conn.execute(
            "SELECT status, COUNT(*) as count FROM students GROUP BY status"
        ).fetchall())

        # Progress buckets
        buckets = {
            "0-39":   0,
            "40-59":  0,
            "60-79":  0,
            "80-100": 0,
        }
        for r in conn.execute("SELECT percentage FROM students").fetchall():
            p = r["percentage"] or 0
            if p <= 39:
                buckets["0-39"]   += 1
            elif p <= 59:
                buckets["40-59"]  += 1
            elif p <= 79:
                buckets["60-79"]  += 1
            else:
                buckets["80-100"] += 1

        # Avg progress
        avg_row = conn.execute("SELECT AVG(percentage) as avg FROM students").fetchone()
        avg_progress = round(avg_row["avg"] or 0, 1)

        return ok({
            "by_course":    by_course,
            "by_status":    by_status,
            "progress_buckets": [
                {"range": k, "count": v} for k, v in buckets.items()
            ],
            "avg_progress": avg_progress,
        })
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Attendance overview ────────────────────────────────────────────────────────

@rep_bp.route("/attendance", methods=["GET"])
@require_auth
def attendance_overview():
    """
    GET /api/reports/attendance?month=2024-05
    Attendance summary across all employees for a month.
    """
    conn = get_db()
    try:
        today = date.today()
        month = request.args.get("month", today.strftime("%Y-%m"))

        rows = conn.execute(
            """SELECT e.id, e.name, e.role, e.dept,
                      COALESCE(a.present,0) as present,
                      COALESCE(a.absent,0)  as absent,
                      COALESCE(a.late,0)    as late
               FROM employees e
               LEFT JOIN attendance a ON e.id=a.emp_id AND a.month=?
               ORDER BY e.name""",
            (month,),
        ).fetchall()

        data = rows_to_list(rows)
        total_present = sum(r["present"] for r in data)
        total_absent  = sum(r["absent"]  for r in data)
        total_late    = sum(r["late"]    for r in data)

        return ok({
            "month":         month,
            "employees":     data,
            "total_present": total_present,
            "total_absent":  total_absent,
            "total_late":    total_late,
        })
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Course performance ─────────────────────────────────────────────────────────

@rep_bp.route("/courses", methods=["GET"])
@require_auth
def course_performance():
    """
    GET /api/reports/courses
    Per-course metrics: enrollment rate, revenue, student count.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT c.id, c.name, c.category, c.fee, c.seats, c.enrolled,
                      c.status, c.duration,
                      COALESCE(e.name,'Unassigned') as trainer_name,
                      (c.fee * c.enrolled) as revenue,
                      ROUND(CAST(c.enrolled AS NUMERIC) / NULLIF(c.seats,0) * 100, 1) as fill_pct
               FROM courses c
               LEFT JOIN employees e ON c.assigned_to=e.id
               ORDER BY revenue DESC"""
        ).fetchall()

        # Active students per course
        stu_counts = {
            r["course"]: r["count"]
            for r in conn.execute(
                "SELECT course, COUNT(*) as count FROM students GROUP BY course"
            ).fetchall()
        }

        data = []
        for r in rows:
            d = dict(r)
            d["student_count"] = stu_counts.get(d["name"], 0)
            data.append(d)

        return ok(data)
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Employee overview ─────────────────────────────────────────────────────────

@rep_bp.route("/employees", methods=["GET"])
@require_auth
def employee_overview():
    """
    GET /api/reports/employees
    Employee stats: by dept, by status, salary totals.
    """
    conn = get_db()
    try:
        by_dept   = rows_to_list(conn.execute(
            "SELECT dept, COUNT(*) as count FROM employees GROUP BY dept ORDER BY count DESC"
        ).fetchall())

        by_status = rows_to_list(conn.execute(
            "SELECT status, COUNT(*) as count FROM employees GROUP BY status"
        ).fetchall())

        payroll_row = conn.execute(
            "SELECT SUM(salary) as total_salary, SUM(bonus) as total_bonus, AVG(salary) as avg_salary FROM employees"
        ).fetchone()

        return ok({
            "by_dept":      by_dept,
            "by_status":    by_status,
            "total_salary": payroll_row["total_salary"] or 0,
            "total_bonus":  payroll_row["total_bonus"]  or 0,
            "avg_salary":   round(payroll_row["avg_salary"] or 0, 2),
        })
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Full report (all in one) ──────────────────────────────────────────────────

@rep_bp.route("/full", methods=["GET"])
@require_auth
def full_report():
    """
    GET /api/reports/full
    Combines dashboard + revenue + students + employees in a single response.
    """
    conn = get_db()
    try:
        # --- Dashboard KPIs ---
        emp_count  = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        stu_count  = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        crs_count  = conn.execute("SELECT COUNT(*) FROM courses WHERE status='active'").fetchone()[0]
        comp_count = conn.execute("SELECT COUNT(*) FROM students WHERE completed=1").fetchone()[0]
        rev        = conn.execute("SELECT COALESCE(SUM(fee*enrolled),0) FROM courses").fetchone()[0]

        # --- Revenue by course ---
        rev_by_course = rows_to_list(conn.execute(
            "SELECT name, category, (fee*enrolled) as revenue FROM courses ORDER BY revenue DESC"
        ).fetchall())

        # --- Students by course ---
        stu_by_course = rows_to_list(conn.execute(
            "SELECT course, COUNT(*) as count FROM students GROUP BY course"
        ).fetchall())

        # --- Employees by dept ---
        emp_by_dept = rows_to_list(conn.execute(
            "SELECT dept, COUNT(*) as count FROM employees GROUP BY dept"
        ).fetchall())

        # --- Top students by progress ---
        top_students = rows_to_list(conn.execute(
            "SELECT id,name,course,percentage FROM students ORDER BY percentage DESC LIMIT 5"
        ).fetchall())

        return ok({
            "kpis": {
                "employees":  emp_count,
                "students":   stu_count,
                "courses":    crs_count,
                "completed":  comp_count,
                "revenue":    rev,
            },
            "revenue_by_course": rev_by_course,
            "students_by_course": stu_by_course,
            "employees_by_dept": emp_by_dept,
            "top_students": top_students,
        })
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()
