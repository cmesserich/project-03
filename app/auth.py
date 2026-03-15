# auth.py
# Project 03 — Touchgrass
#
# Authentication utilities: password hashing, session management,
# and FastAPI dependency functions for protecting routes.
#
# Public API:
#   hash_password(password)                         → hashed string
#   verify_password(plain, hashed)                  → bool
#   create_session(user_id, ip, user_agent)         → session token
#   validate_session(token)                         → user dict | None
#   invalidate_session(token)                       → None
#   get_current_user(request)                       → user dict   [Depends]
#   require_admin(request, user)                    → user dict   [Depends]
#
# Session storage: server-side rows in app3.user_sessions.
# Tokens are 32-byte URL-safe random strings (256 bits of entropy).
# Passwords are bcrypt-hashed via passlib.

import os
import secrets
import ipaddress
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import text

from db import get_engine

SESSION_COOKIE = "tg_session"
SESSION_DAYS = 7


# ─────────────────────────────────────────────
# PASSWORD
# ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ─────────────────────────────────────────────
# SESSION MANAGEMENT
# ─────────────────────────────────────────────

def create_session(
    user_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """Creates a new session row and returns the token string."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO app3.user_sessions
                (session_token, user_id, expires_at, ip_address, user_agent)
            VALUES
                (:token, :user_id, :expires_at, :ip, :ua)
        """), {
            "token":      token,
            "user_id":    user_id,
            "expires_at": expires_at,
            "ip":         ip_address,
            "ua":         user_agent,
        })
    return token


def validate_session(token: str) -> Optional[dict]:
    """
    Returns a user dict if the session token is valid, active, and unexpired.
    Returns None otherwise.
    """
    with get_engine().connect() as conn:
        row = conn.execute(text("""
            SELECT
                u.id, u.username, u.email, u.is_admin, u.is_active,
                s.expires_at, s.is_active AS session_active
            FROM app3.user_sessions s
            JOIN app3.users u ON u.id = s.user_id
            WHERE s.session_token = :token
        """), {"token": token}).fetchone()

    if row is None:
        return None
    if not row.session_active or not row.is_active:
        return None
    if row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None

    return {
        "id":       str(row.id),
        "username": row.username,
        "email":    row.email,
        "is_admin": row.is_admin,
    }


def invalidate_session(token: str) -> None:
    """Marks a session as inactive (logout)."""
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE app3.user_sessions
            SET is_active = FALSE
            WHERE session_token = :token
        """), {"token": token})


# ─────────────────────────────────────────────
# IP HELPERS
# ─────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    """
    Extracts the real client IP.
    Reads X-Forwarded-For first (set by nginx/caddy reverse proxy),
    falls back to direct socket address.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_allowed_admin_ip(ip: str) -> bool:
    """
    Checks whether the IP falls within ADMIN_ALLOWED_NETWORKS.
    Env var accepts comma-separated CIDRs, e.g. "192.168.68.0/24,10.0.0.1/32".
    Defaults to 0.0.0.0/0 (allow all) — restrict via env var when ready.
    """
    allowed = os.getenv("ADMIN_ALLOWED_NETWORKS", "0.0.0.0/0")
    try:
        client = ipaddress.ip_address(ip)
        for cidr in allowed.split(","):
            try:
                network = ipaddress.ip_network(cidr.strip(), strict=False)
                if client in network:
                    return True
            except (ValueError, TypeError):
                continue
    except ValueError:
        return False
    return False


# ─────────────────────────────────────────────
# FASTAPI DEPENDENCIES
# ─────────────────────────────────────────────

def get_current_user(request: Request) -> dict:
    """
    FastAPI dependency. Reads the session cookie, validates it, and
    returns the user dict. Raises HTTP 401 if missing or invalid.

    Usage:
        @app.get("/protected")
        async def route(user: dict = Depends(get_current_user)): ...
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = validate_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return user


def require_admin(
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    FastAPI dependency. Extends get_current_user with two additional checks:
      1. Request IP must fall within ADMIN_ALLOWED_NETWORKS
      2. User must have is_admin = True

    Usage:
        @router.get("/admin/users")
        async def users(admin: dict = Depends(require_admin)): ...
    """
    ip = _get_client_ip(request)
    if not _is_allowed_admin_ip(ip):
        raise HTTPException(
            status_code=403,
            detail="Admin access is restricted to the local network.",
        )
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return user
