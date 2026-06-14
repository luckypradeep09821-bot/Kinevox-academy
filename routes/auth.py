"""
routes/auth.py
==============
Authentication endpoints:
  POST /api/auth/login          — get JWT token
  POST /api/auth/logout         — (stateless; client drops token)
  POST /api/auth/change-password
  GET  /api/auth/me             — current user info
"""

import hashlib
from flask import Blueprint, request

from db.database import get_db
from middleware.auth import generate_token, require_auth
from utils.helpers import ok, err, row_to_dict

auth_bp = Blueprint("auth", __name__)


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


# ── Login ─────────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["POST"])
def login():
    """
    POST /api/auth/login
    Body: { "username": "admin", "password": "Kinevox123" }
    Returns: { token, user }
    """
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        return err("Username and password are required")

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if not user or user["password"] != _hash(password):
            return err("Incorrect username or password", 401)

        token = generate_token(user["id"], user["username"])

        return ok(
            {
                "token": token,
                "user": {
                    "id":       user["id"],
                    "username": user["username"],
                    "role":     user["role"],
                },
            },
            "Login successful",
        )
    finally:
        conn.close()


# ── Logout ────────────────────────────────────────────────────────────────────

@auth_bp.route("/logout", methods=["POST"])
@require_auth
def logout():
    """Stateless logout — client should discard the token."""
    return ok(message="Logged out successfully")


# ── Current user ──────────────────────────────────────────────────────────────

@auth_bp.route("/me", methods=["GET"])
@require_auth
def me():
    """GET /api/auth/me — returns the authenticated user's profile."""
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, username, role, created_at FROM users WHERE id = ?",
            (request.user["sub"],),
        ).fetchone()

        if not user:
            return err("User not found", 404)

        return ok(row_to_dict(user))
    finally:
        conn.close()


# ── Change password ────────────────────────────────────────────────────────────

@auth_bp.route("/change-password", methods=["POST"])
@require_auth
def change_password():
    """
    POST /api/auth/change-password
    Body: { "current_password": "...", "new_password": "..." }
    """
    body = request.get_json(silent=True) or {}
    current_pw = body.get("current_password") or ""
    new_pw     = body.get("new_password") or ""

    if not current_pw or not new_pw:
        return err("Both current_password and new_password are required")

    if len(new_pw) < 6:
        return err("New password must be at least 6 characters")

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (request.user["sub"],)
        ).fetchone()

        if not user or user["password"] != _hash(current_pw):
            return err("Current password is incorrect", 401)

        conn.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (_hash(new_pw), request.user["sub"]),
        )
        conn.commit()
        return ok(message="Password changed successfully")
    finally:
        conn.close()
