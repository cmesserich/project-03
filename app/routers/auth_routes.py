# routers/auth_routes.py
# Project 03 — Touchgrass
#
# Auth routes: login, register, logout.
# All form-based, server-side rendered via Jinja2.
#
# Routes:
#   GET  /auth/login     → login form
#   POST /auth/login     → validate credentials, set cookie, redirect
#   GET  /auth/register  → register form
#   POST /auth/register  → create account, set cookie, redirect
#   POST /auth/logout    → invalidate session, clear cookie, redirect

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import (
    SESSION_COOKIE,
    create_session,
    hash_password,
    invalidate_session,
    validate_session,
    verify_password,
)
from db import (
    create_user,
    get_user_by_email,
    get_user_by_username,
    update_last_login,
)

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)

router = APIRouter(prefix="/auth")

_COOKIE_OPTS = dict(
    httponly=True,
    samesite="lax",
    max_age=7 * 24 * 3600,
    secure=False,  # set True when serving over HTTPS
)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    # Already logged in → send home
    token = request.cookies.get(SESSION_COOKIE)
    if token and validate_session(token):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {
        "request": request,
        "mode":    "login",
        "next":    next,
        "error":   None,
    })


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str     = Form(default="/"),
):
    def fail(msg: str, status: int = 401):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "mode":    "login",
            "next":    next,
            "error":   msg,
        }, status_code=status)

    user = get_user_by_username(username)
    if not user or not verify_password(password, user["password_hash"]):
        return fail("Invalid username or password.")
    if not user["is_active"]:
        return fail("Account is deactivated. Contact the administrator.", 403)

    token = create_session(
        user["id"],
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    update_last_login(user["id"])

    # Only allow relative redirects to prevent open-redirect attacks
    safe_next = next if next.startswith("/") else "/"
    response = RedirectResponse(url=safe_next, status_code=302)
    response.set_cookie(key=SESSION_COOKIE, value=token, **_COOKIE_OPTS)
    return response


# ─────────────────────────────────────────────
# REGISTER
# ─────────────────────────────────────────────

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token and validate_session(token):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {
        "request": request,
        "mode":    "register",
        "next":    "/",
        "error":   None,
    })


@router.post("/register")
async def register(
    request: Request,
    username:         str = Form(...),
    email:            str = Form(...),
    password:         str = Form(...),
    confirm_password: str = Form(...),
):
    def fail(msg: str, status: int = 400):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "mode":    "register",
            "next":    "/",
            "error":   msg,
        }, status_code=status)

    if len(username) < 3:
        return fail("Username must be at least 3 characters.")
    if len(username) > 50:
        return fail("Username must be 50 characters or fewer.")
    if password != confirm_password:
        return fail("Passwords do not match.")
    if len(password) < 8:
        return fail("Password must be at least 8 characters.")
    if get_user_by_username(username):
        return fail("Username already taken.")
    if get_user_by_email(email):
        return fail("An account with that email already exists.")

    try:
        user_id = create_user(username, email, hash_password(password))
    except Exception:
        return fail("Registration failed. Please try again.", 500)

    token = create_session(
        user_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(key=SESSION_COOKIE, value=token, **_COOKIE_OPTS)
    return response


# ─────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────

@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        invalidate_session(token)
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response
