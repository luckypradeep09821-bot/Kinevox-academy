"""
routes/uploads.py
==================
File upload endpoints:

  POST /api/uploads/employee/<id>/photo       — employee profile photo
  POST /api/uploads/student/<id>/photo        — student profile photo
  POST /api/uploads/employee/<id>/document    — employee document (sign|id_doc|resume|other)
  DELETE /api/uploads/employee/<id>/photo     — remove photo
  DELETE /api/uploads/student/<id>/photo      — remove photo
"""

import os
import uuid
import mimetypes
from flask import Blueprint, request, current_app

from db.database import get_db
from middleware.auth import require_auth
from utils.helpers import ok, err, not_found, server_error
from utils.email_notify import notify_document_upload, notify_documents_batch

upload_bp = Blueprint("uploads", __name__)

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_DOC_EXT   = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "doc", "docx"}

DOC_TYPE_LABELS = {
    "sign":    "Signature",
    "id_doc":  "Identity Document (Aadhar/PAN)",
    "resume":  "Resume / CV",
    "other":   "Other Document",
}


def _allowed(filename: str, allowed: set) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def _save_file(file, subfolder: str, original_name: str = None) -> tuple[str, str]:
    """
    Save uploaded file into uploads/<subfolder>/.
    Returns (relative_url, absolute_filepath).
    """
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder)
    os.makedirs(folder, exist_ok=True)
    ext      = file.filename.rsplit(".", 1)[1].lower()
    safe_orig = (original_name or file.filename).replace(" ", "_")
    filename = f"{uuid.uuid4().hex[:8]}_{safe_orig}"
    if not filename.lower().endswith(f".{ext}"):
        filename = f"{filename}.{ext}"
    filepath = os.path.join(folder, filename)
    file.save(filepath)
    url = f"/uploads/{subfolder}/{filename}"
    return url, filepath


# ── Employee photo ─────────────────────────────────────────────────────────────

@upload_bp.route("/employee/<emp_id>/photo", methods=["POST"])
@require_auth
def upload_emp_photo(emp_id):
    conn = get_db()
    try:
        emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        if not emp:
            return not_found("Employee")

        if "file" not in request.files:
            return err("No file provided")

        f = request.files["file"]
        if not f.filename:
            return err("Empty filename")
        if not _allowed(f.filename, ALLOWED_IMAGE_EXT):
            return err(f"Allowed image types: {', '.join(ALLOWED_IMAGE_EXT)}")

        url, _ = _save_file(f, f"employees/{emp_id}")
        conn.execute(
            "UPDATE employees SET photo=?, updated_at=datetime('now') WHERE id=?",
            (url, emp_id),
        )
        conn.commit()
        return ok({"url": url}, "Photo uploaded")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Student photo ──────────────────────────────────────────────────────────────

@upload_bp.route("/student/<stu_id>/photo", methods=["POST"])
@require_auth
def upload_stu_photo(stu_id):
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM students WHERE id=?", (stu_id,)).fetchone():
            return not_found("Student")

        if "file" not in request.files:
            return err("No file provided")

        f = request.files["file"]
        if not f.filename:
            return err("Empty filename")
        if not _allowed(f.filename, ALLOWED_IMAGE_EXT):
            return err(f"Allowed image types: {', '.join(ALLOWED_IMAGE_EXT)}")

        url, _ = _save_file(f, f"students/{stu_id}")
        conn.execute(
            "UPDATE students SET photo=?, updated_at=datetime('now') WHERE id=?",
            (url, stu_id),
        )
        conn.commit()
        return ok({"url": url}, "Photo uploaded")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()


# ── Employee document ──────────────────────────────────────────────────────────

@upload_bp.route("/employee/<emp_id>/document", methods=["POST"])
@require_auth
def upload_emp_doc(emp_id):
    """
    POST /api/uploads/employee/<id>/document
    Form-data:
      file     — the file
      doc_type — sign | id_doc | resume | other
    Saves to  uploads/employees/<emp_id>/docs/
    Sends an email notification with the file attached.
    """
    conn = get_db()
    try:
        emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        if not emp:
            return not_found("Employee")

        if "file" not in request.files:
            return err("No file provided")

        doc_type = request.form.get("doc_type", "resume")
        if doc_type not in DOC_TYPE_LABELS:
            return err(f"doc_type must be one of: {', '.join(DOC_TYPE_LABELS)}")

        f = request.files["file"]
        if not f.filename:
            return err("Empty filename")
        if not _allowed(f.filename, ALLOWED_DOC_EXT):
            return err(f"Allowed types: {', '.join(ALLOWED_DOC_EXT)}")

        # Save into uploads/employees/<emp_id>/docs/
        subfolder = f"employees/{emp_id}/docs"
        url, filepath = _save_file(f, subfolder, f.filename)

        # Read bytes NOW in the request thread (Render filesystem is ephemeral;
        # the background thread must not re-open a path that may vanish)
        f.stream.seek(0)
        file_bytes = f.stream.read()

        # Persist URL in DB column (sign | id_doc | resume | other)
        col_map = {"sign": "sign", "id_doc": "id_doc", "resume": "resume", "other": "other"}
        col = col_map[doc_type]
        try:
            conn.execute(
                f"UPDATE employees SET {col}=?, updated_at=datetime('now') WHERE id=?",
                (url, emp_id),
            )
            conn.commit()
        except Exception:
            # 'other' column may not exist in older schemas — ignore gracefully
            pass

        # Fire-and-forget email with file attached
        emp_dict = dict(emp)
        notify_document_upload(
            record_type="employee",
            record=emp_dict,
            doc_type_label=DOC_TYPE_LABELS[doc_type],
            file_bytes=file_bytes,
            original_filename=f.filename,
        )

        return ok({"url": url, "doc_type": doc_type}, "Document uploaded")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()



# ── Employee documents (batch) ─────────────────────────────────────────────────

@upload_bp.route("/employee/<emp_id>/documents", methods=["POST"])
@require_auth
def upload_emp_docs_batch(emp_id):
    """
    POST /api/uploads/employee/<id>/documents
    Form-data (multiple files):
      sign     — signature image
      id_doc   — identity document
      resume   — resume/CV
      other    — other document
    Saves all files, then sends ONE combined email with all attachments.
    """
    conn = get_db()
    try:
        emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        if not emp:
            return not_found("Employee")

        uploaded = []   # list of (doc_type_label, file_bytes, original_filename)
        results  = {}

        for doc_type, label in DOC_TYPE_LABELS.items():
            if doc_type not in request.files:
                continue
            f = request.files[doc_type]
            if not f or not f.filename:
                continue
            if not _allowed(f.filename, ALLOWED_DOC_EXT):
                continue

            subfolder = f"employees/{emp_id}/docs"

            # Read bytes NOW in the request thread before saving (ephemeral filesystem safety)
            f.stream.seek(0)
            file_bytes = f.stream.read()

            url, filepath = _save_file(f, subfolder, f.filename)

            # Persist in DB
            col = doc_type  # sign | id_doc | resume | other
            try:
                conn.execute(
                    f"UPDATE employees SET {col}=?, updated_at=datetime('now') WHERE id=?",
                    (url, emp_id),
                )
            except Exception:
                pass

            results[doc_type] = url
            uploaded.append((label, file_bytes, f.filename))

        conn.commit()

        # Send ONE email with all uploaded files attached
        if uploaded:
            notify_documents_batch(
                record_type="employee",
                record=dict(emp),
                documents=uploaded,
            )

        return ok({"uploaded": results}, f"{len(uploaded)} document(s) uploaded")
    except Exception as e:
        return server_error(e)
    finally:
        conn.close()

# ── Delete photo ───────────────────────────────────────────────────────────────

@upload_bp.route("/employee/<emp_id>/photo", methods=["DELETE"])
@require_auth
def delete_emp_photo(emp_id):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE employees SET photo=NULL, updated_at=datetime('now') WHERE id=?",
            (emp_id,),
        )
        conn.commit()
        return ok(message="Photo removed")
    finally:
        conn.close()


@upload_bp.route("/student/<stu_id>/photo", methods=["DELETE"])
@require_auth
def delete_stu_photo(stu_id):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE students SET photo=NULL, updated_at=datetime('now') WHERE id=?",
            (stu_id,),
        )
        conn.commit()
        return ok(message="Photo removed")
    finally:
        conn.close()
