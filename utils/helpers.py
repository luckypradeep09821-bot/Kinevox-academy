"""
utils/helpers.py
=================
Shared helpers: response builders, ID generation, validation.
"""

from flask import jsonify


# ── Response helpers ─────────────────────────────────────────────────────────

def ok(data=None, message: str = "Success", status: int = 200):
    resp = {"success": True, "message": message}
    if data is not None:
        resp["data"] = data
    return jsonify(resp), status


def created(data=None, message: str = "Created"):
    return ok(data, message, 201)


def err(message: str, status: int = 400, details=None):
    resp = {"success": False, "error": message}
    if details:
        resp["details"] = details
    return jsonify(resp), status


def not_found(entity: str = "Resource"):
    return err(f"{entity} not found", 404)


def server_error(exc: Exception):
    return err(f"Internal server error: {str(exc)}", 500)


# ── ID generation ─────────────────────────────────────────────────────────────

def next_id(prefix: str, existing_ids: list[str]) -> str:
    """Generate next sequential ID like EMP004, STU005, CRS006."""
    nums = []
    for id_ in existing_ids:
        try:
            nums.append(int(id_.replace(prefix, "")))
        except ValueError:
            pass
    next_num = max(nums, default=0) + 1
    return f"{prefix}{next_num:03d}"


# ── Row -> dict ───────────────────────────────────────────────────────────────

def row_to_dict(row) -> dict:
    """Convert an sqlite3.Row to a plain dict."""
    return dict(row) if row else None


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ── Validation ────────────────────────────────────────────────────────────────

def require_fields(data: dict, fields: list[str]) -> str | None:
    """Return error message if any required field is missing/empty."""
    for f in fields:
        if not data.get(f):
            return f"Field '{f}' is required"
    return None


# ── Payroll ───────────────────────────────────────────────────────────────────

def calc_payroll(salary: int, bonus: int) -> dict:
    """Calculate payroll deductions and net pay."""
    gross = salary + bonus
    pf    = round(salary * 0.12)   # PF on basic
    tax   = round(gross * 0.05)    # Tax on gross
    net   = gross - pf - tax
    return {
        "basic":   salary,
        "bonus":   bonus,
        "gross":   gross,
        "pf":      pf,
        "tax":     tax,
        "net":     net,
    }
