"""
routes/courses.py
==================
Course management endpoints:

  GET    /api/courses            — list all courses
  POST   /api/courses            — create course
  GET    /api/courses/<id>       — get single course
  PUT    /api/courses/<id>       — update course
  DELETE /api/courses/<id>       — delete course
  PUT    /api/courses/<id>/enrollment — update enrolled count
"""

from flask import Blueprint, request

from db.database import get_db
from middleware.auth import require_auth
from utils.helpers import (
    ok, err, created, not_found, server_error,
    row_to_dict, rows_to_list, next_id, require_fields
)

crs_bp = Blueprint("courses", __name__)


def _enrich_course(conn, c: dict) -> dict:
    """Attach trainer info to course dict."""
    if c.get("assigned_to"):
        t = conn.execute(
            "SELECT id, name, role FROM employees WHERE id=?", (c["assigned_to"],)
        ).fetchone()
        c["trainer"] = dict(t) if t else None
    else:
        c["trainer"] = None
    return c


# ── List / Create ──────────────────────────────────────────────────────────────

@crs_bp.route("", methods=["GET"])
@require_auth
def list_courses():
    """
    GET /api/courses
    Query params: ?search=<text>&status=<active|upcoming|closed>&category=<cat>
    """
    q        = request.args.get("search", "").lower()
    status   = request.args.get("status", "")
    category = request.args.get("category", "")

    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM courses ORDER BY name").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if q and q not in d.get("name", "").lower() and q not in d.get("category", "").lower():
                continue
            if status and d.get("status") != status:
                continue
            if category and d.get("category") != category:
                continue
            result.append(_enrich_course(conn, d))
        return ok(result)
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


@crs_bp.route("", methods=["POST"])
@require_auth
def create_course():
    """POST /api/courses"""
    body  = request.get_json(silent=True) or {}
    error = require_fields(body, ["name"])
    if error:
        return err(error)

    conn = get_db()
    try:
        existing_ids = [r["id"] for r in conn.execute("SELECT id FROM courses").fetchall()]
        crs_id = body.get("id") or next_id("CRS", existing_ids)

        if conn.execute("SELECT 1 FROM courses WHERE id=?", (crs_id,)).fetchone():
            return err(f"Course ID '{crs_id}' already exists")

        conn.execute(
            """INSERT INTO courses
               (id,name,category,duration,fee,seats,enrolled,assigned_to,description,status)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                crs_id,
                body["name"],
                body.get("category", "Programming"),
                body.get("duration", ""),
                int(body.get("fee") or 0),
                int(body.get("seats") or 0),
                int(body.get("enrolled") or 0),
                body.get("assignedTo") or body.get("assigned_to") or None,
                body.get("description", ""),
                body.get("status", "active"),
            ),
        )
        conn.commit()

        new_c = dict(conn.execute("SELECT * FROM courses WHERE id=?", (crs_id,)).fetchone())
        return created(_enrich_course(conn, new_c), "Course created")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Single course ─────────────────────────────────────────────────────────────

@crs_bp.route("/<crs_id>", methods=["GET"])
@require_auth
def get_course(crs_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM courses WHERE id=?", (crs_id,)).fetchone()
        if not row:
            return not_found("Course")
        return ok(_enrich_course(conn, dict(row)))
    finally:
        conn.close()


@crs_bp.route("/<crs_id>", methods=["PUT"])
@require_auth
def update_course(crs_id):
    conn = get_db()
    try:
        existing = conn.execute("SELECT * FROM courses WHERE id=?", (crs_id,)).fetchone()
        if not existing:
            return not_found("Course")

        body = request.get_json(silent=True) or {}

        conn.execute(
            """UPDATE courses SET
               name=?, category=?, duration=?, fee=?, seats=?, enrolled=?,
               assigned_to=?, description=?, status=?, updated_at=datetime('now')
               WHERE id=?""",
            (
                body.get("name", existing["name"]),
                body.get("category", existing["category"]),
                body.get("duration", existing["duration"]),
                int(body.get("fee") or existing["fee"] or 0),
                int(body.get("seats") or existing["seats"] or 0),
                int(body.get("enrolled") or existing["enrolled"] or 0),
                body.get("assignedTo") or body.get("assigned_to") or existing["assigned_to"],
                body.get("description", existing["description"]),
                body.get("status", existing["status"]),
                crs_id,
            ),
        )
        conn.commit()

        updated = dict(conn.execute("SELECT * FROM courses WHERE id=?", (crs_id,)).fetchone())
        return ok(_enrich_course(conn, updated), "Course updated")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


@crs_bp.route("/<crs_id>", methods=["DELETE"])
@require_auth
def delete_course(crs_id):
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM courses WHERE id=?", (crs_id,)).fetchone():
            return not_found("Course")
        conn.execute("DELETE FROM courses WHERE id=?", (crs_id,))
        conn.commit()
        return ok(message="Course deleted")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Enrollment count ──────────────────────────────────────────────────────────

@crs_bp.route("/<crs_id>/enrollment", methods=["PUT"])
@require_auth
def update_enrollment(crs_id):
    """
    PUT /api/courses/<id>/enrollment
    Body: { "enrolled": 10 }  OR  { "delta": 1 }  (increment/decrement)
    """
    conn = get_db()
    try:
        course = conn.execute("SELECT * FROM courses WHERE id=?", (crs_id,)).fetchone()
        if not course:
            return not_found("Course")

        body = request.get_json(silent=True) or {}

        if "enrolled" in body:
            new_enrolled = int(body["enrolled"])
        elif "delta" in body:
            new_enrolled = max(0, (course["enrolled"] or 0) + int(body["delta"]))
        else:
            return err("Provide 'enrolled' or 'delta' field")

        if new_enrolled > (course["seats"] or 0):
            return err(f"Cannot exceed seat capacity ({course['seats']})")

        conn.execute(
            "UPDATE courses SET enrolled=?, updated_at=datetime('now') WHERE id=?",
            (new_enrolled, crs_id),
        )
        conn.commit()
        return ok({"enrolled": new_enrolled, "seats": course["seats"]}, "Enrollment updated")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()
