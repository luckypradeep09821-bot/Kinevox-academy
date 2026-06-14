"""
routes/students.py
===================
Student management endpoints:

  GET    /api/students                   — list (with filters & sort)
  POST   /api/students                   — create
  GET    /api/students/<id>              — get single
  PUT    /api/students/<id>              — update
  DELETE /api/students/<id>              — delete
  POST   /api/students/<id>/complete     — mark as completed
  PUT    /api/students/<id>/progress     — update progress %
  GET    /api/students/completed         — completed students only
  GET    /api/students/<id>/certificate  — get/issue certificate record
"""

from flask import Blueprint, request
from datetime import date

from db.database import get_db
from middleware.auth import require_auth
from utils.helpers import (
    ok, err, created, not_found, server_error,
    row_to_dict, rows_to_list, next_id, require_fields
)
from utils.email_notify import notify_new_record

stu_bp = Blueprint("students", __name__)


def _enrich_student(conn, s: dict) -> dict:
    """Attach trainer name to a student dict."""
    if s.get("assigned_to"):
        trainer_row = conn.execute(
            "SELECT name FROM employees WHERE id=?", (s["assigned_to"],)
        ).fetchone()
        s["trainer_name"] = trainer_row["name"] if trainer_row else "Unknown"
    else:
        s["trainer_name"] = "Unassigned"
    return s


# ── List / Create ──────────────────────────────────────────────────────────────

@stu_bp.route("", methods=["GET"])
@require_auth
def list_students():
    """
    GET /api/students
    Query params:
      search, status, course, trainer_id, institution,
      min_pct, max_pct, enroll_date,
      sort_by (name|name_desc|doj|doj_desc|percentage|percentage_desc)
    """
    q            = request.args.get("search", "").lower()
    status       = request.args.get("status", "")
    course       = request.args.get("course", "")
    trainer_id   = request.args.get("trainer_id", "")
    institution  = request.args.get("institution", "")
    min_pct      = request.args.get("min_pct", type=int)
    max_pct      = request.args.get("max_pct", type=int)
    enroll_date  = request.args.get("enroll_date", "")
    sort_by      = request.args.get("sort_by", "name")

    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM students").fetchall()
        result = []
        for r in rows:
            d = _enrich_student(conn, dict(r))

            if q and not any(
                q in (d.get(f) or "").lower()
                for f in ("name", "course", "id", "institution", "email")
            ):
                continue
            if status and d.get("status") != status:
                continue
            if course and d.get("course") != course:
                continue
            if trainer_id and d.get("assigned_to") != trainer_id:
                continue
            if institution and d.get("institution") != institution:
                continue
            if enroll_date and d.get("enroll_date") != enroll_date:
                continue
            pct = d.get("percentage", 0) or 0
            if min_pct is not None and pct < min_pct:
                continue
            if max_pct is not None and pct > max_pct:
                continue

            result.append(d)

        # Sorting
        reverse = sort_by.endswith("_desc")
        key_map = {
            "name":             lambda x: (x.get("name") or "").lower(),
            "name_desc":        lambda x: (x.get("name") or "").lower(),
            "doj":              lambda x: x.get("enroll_date") or "",
            "doj_desc":         lambda x: x.get("enroll_date") or "",
            "percentage":       lambda x: x.get("percentage") or 0,
            "percentage_desc":  lambda x: x.get("percentage") or 0,
        }
        key_fn = key_map.get(sort_by, lambda x: (x.get("name") or "").lower())
        result.sort(key=key_fn, reverse=reverse)

        return ok(result)
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


@stu_bp.route("", methods=["POST"])
@require_auth
def create_student():
    """POST /api/students"""
    body  = request.get_json(silent=True) or {}
    error = require_fields(body, ["name"])
    if error:
        return err(error)

    conn = get_db()
    try:
        existing_ids = [r["id"] for r in conn.execute("SELECT id FROM students").fetchall()]
        stu_id = body.get("id") or next_id("STU", existing_ids)

        if conn.execute("SELECT 1 FROM students WHERE id=?", (stu_id,)).fetchone():
            return err(f"Student ID '{stu_id}' already exists")

        progress = int(body.get("progress") or 0)
        status   = body.get("status", "active")
        completed = 1 if status == "completed" or progress == 100 else 0

        # Resolve trainer name
        assigned_to  = body.get("assigned_to", "")
        trainer_name = body.get("trainer", "")
        if assigned_to and not trainer_name:
            t = conn.execute("SELECT name FROM employees WHERE id=?", (assigned_to,)).fetchone()
            trainer_name = t["name"] if t else ""

        conn.execute(
            """INSERT INTO students
               (id,name,email,phone,dob,institution,course,assigned_to,trainer,
                enroll_date,progress,percentage,status,completed)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                stu_id,
                body["name"],
                body.get("email", ""),
                body.get("phone", ""),
                body.get("dob", ""),
                body.get("institution", ""),
                body.get("course", ""),
                assigned_to,
                trainer_name,
                body.get("enrollDate") or body.get("enroll_date") or date.today().isoformat(),
                progress,
                progress,
                status,
                completed,
            ),
        )
        conn.commit()

        new_stu = dict(conn.execute("SELECT * FROM students WHERE id=?", (stu_id,)).fetchone())
        enriched = _enrich_student(conn, new_stu)
        notify_new_record("student", enriched)
        return created(enriched, "Student created")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Single student ─────────────────────────────────────────────────────────────

@stu_bp.route("/<stu_id>", methods=["GET"])
@require_auth
def get_student(stu_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM students WHERE id=?", (stu_id,)).fetchone()
        if not row:
            return not_found("Student")
        return ok(_enrich_student(conn, dict(row)))
    finally:
        conn.close()


@stu_bp.route("/<stu_id>", methods=["PUT"])
@require_auth
def update_student(stu_id):
    conn = get_db()
    try:
        existing = conn.execute("SELECT * FROM students WHERE id=?", (stu_id,)).fetchone()
        if not existing:
            return not_found("Student")

        body     = request.get_json(silent=True) or {}
        progress = int(body.get("progress") or existing["progress"] or 0)
        status   = body.get("status", existing["status"])
        completed = 1 if status == "completed" or progress == 100 else int(existing["completed"])

        assigned_to  = body.get("assigned_to", existing["assigned_to"])
        trainer_name = body.get("trainer", existing["trainer"] or "")
        if assigned_to and not trainer_name:
            t = conn.execute("SELECT name FROM employees WHERE id=?", (assigned_to,)).fetchone()
            trainer_name = t["name"] if t else ""

        conn.execute(
            """UPDATE students SET
               name=?, email=?, phone=?, dob=?, institution=?, course=?,
               assigned_to=?, trainer=?, enroll_date=?, progress=?,
               percentage=?, status=?, completed=?, updated_at=datetime('now')
               WHERE id=?""",
            (
                body.get("name", existing["name"]),
                body.get("email", existing["email"]),
                body.get("phone", existing["phone"]),
                body.get("dob", existing["dob"]),
                body.get("institution", existing["institution"]),
                body.get("course", existing["course"]),
                assigned_to,
                trainer_name,
                body.get("enrollDate") or body.get("enroll_date") or existing["enroll_date"],
                progress,
                progress,
                status,
                completed,
                stu_id,
            ),
        )
        conn.commit()

        updated = dict(conn.execute("SELECT * FROM students WHERE id=?", (stu_id,)).fetchone())
        return ok(_enrich_student(conn, updated), "Student updated")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


@stu_bp.route("/<stu_id>", methods=["DELETE"])
@require_auth
def delete_student(stu_id):
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM students WHERE id=?", (stu_id,)).fetchone():
            return not_found("Student")
        conn.execute("DELETE FROM students WHERE id=?", (stu_id,))
        conn.commit()
        return ok(message="Student deleted")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Progress update ───────────────────────────────────────────────────────────

@stu_bp.route("/<stu_id>/progress", methods=["PUT"])
@require_auth
def update_progress(stu_id):
    """
    PUT /api/students/<id>/progress
    Body: { "progress": 80 }
    """
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM students WHERE id=?", (stu_id,)).fetchone():
            return not_found("Student")

        body     = request.get_json(silent=True) or {}
        progress = min(100, max(0, int(body.get("progress") or 0)))
        completed = 1 if progress == 100 else 0
        status    = "completed" if progress == 100 else "active"

        conn.execute(
            """UPDATE students
               SET progress=?, percentage=?, completed=?, status=?, updated_at=datetime('now')
               WHERE id=?""",
            (progress, progress, completed, status, stu_id),
        )
        conn.commit()
        return ok({"progress": progress, "completed": bool(completed)}, "Progress updated")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Mark complete ─────────────────────────────────────────────────────────────

@stu_bp.route("/<stu_id>/complete", methods=["POST"])
@require_auth
def mark_complete(stu_id):
    """POST /api/students/<id>/complete — marks student as 100% completed."""
    conn = get_db()
    try:
        stu = conn.execute("SELECT * FROM students WHERE id=?", (stu_id,)).fetchone()
        if not stu:
            return not_found("Student")

        conn.execute(
            """UPDATE students
               SET progress=100, percentage=100, completed=1, status='completed',
                   updated_at=datetime('now')
               WHERE id=?""",
            (stu_id,),
        )

        # Auto-issue certificate if not already issued
        cert_no = f"KVI-{stu_id}-{date.today().year}"
        conn.execute(
            """INSERT OR IGNORE INTO certificates (student_id, cert_no, course)
               VALUES (?,?,?)""",
            (stu_id, cert_no, stu["course"]),
        )
        conn.commit()

        return ok(
            {"cert_no": cert_no, "issued_on": date.today().isoformat()},
            "Student marked as completed. Certificate issued.",
        )
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Completed students ────────────────────────────────────────────────────────

@stu_bp.route("/completed", methods=["GET"])
@require_auth
def completed_students():
    """GET /api/students/completed"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM students WHERE completed=1 OR status='completed' ORDER BY name"
        ).fetchall()
        return ok([_enrich_student(conn, dict(r)) for r in rows])
    finally:
        conn.close()


# ── Certificate ───────────────────────────────────────────────────────────────

@stu_bp.route("/<stu_id>/certificate", methods=["GET"])
@require_auth
def get_certificate(stu_id):
    """
    GET /api/students/<id>/certificate
    Returns the certificate record (or issues one if student is completed).
    """
    conn = get_db()
    try:
        stu = conn.execute("SELECT * FROM students WHERE id=?", (stu_id,)).fetchone()
        if not stu:
            return not_found("Student")

        if not stu["completed"]:
            return err("Student has not completed the course yet", 400)

        cert = conn.execute(
            "SELECT * FROM certificates WHERE student_id=?", (stu_id,)
        ).fetchone()

        if not cert:
            # Auto-issue
            cert_no = f"KVI-{stu_id}-{date.today().year}"
            conn.execute(
                "INSERT INTO certificates (student_id,cert_no,course) VALUES (?,?,?)",
                (stu_id, cert_no, stu["course"]),
            )
            conn.commit()
            cert = conn.execute(
                "SELECT * FROM certificates WHERE student_id=?", (stu_id,)
            ).fetchone()

        cert_data = dict(cert)
        cert_data["student_name"] = stu["name"]
        cert_data["course"]       = stu["course"]
        cert_data["institution"]  = stu["institution"]

        return ok(cert_data)
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()
