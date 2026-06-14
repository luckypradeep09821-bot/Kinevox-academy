"""
middleware/auth.py
==================
JWT-based authentication decorator.
"""

import jwt
import hashlib
from functools import wraps
from flask import request, jsonify, current_app

from db.database import get_db


def _hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def generate_token(user_id: int, username: str) -> str:
    """Generate a signed JWT access token."""
    from datetime import datetime, timedelta, timezone
    expiry = datetime.now(timezone.utc) + timedelta(
        hours=current_app.config.get("JWT_EXPIRY_HOURS", 8)
    )
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expiry,
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def verify_token(token: str) -> dict | None:
    """Decode and verify a JWT. Returns payload dict or None on failure."""
    try:
        return jwt.decode(
            token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def require_auth(f):
    """Decorator: blocks requests without a valid Bearer token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Authentication required"}), 401

        token = auth_header.split(" ", 1)[1]
        payload = verify_token(token)
        if payload is None:
            return jsonify({"error": "Token is invalid or expired"}), 401

        # Attach user info to request context (coerce sub back to int)
        payload["sub"] = int(payload["sub"])
        request.user = payload
        return f(*args, **kwargs)

    return decorated
