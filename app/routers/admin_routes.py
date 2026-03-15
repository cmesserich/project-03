# routers/admin_routes.py
# Project 03 — Touchgrass
#
# Admin dashboard routes. All routes require:
#   1. Valid session (via get_current_user inside require_admin)
#   2. is_admin = True on the user row
#   3. Request IP within ADMIN_ALLOWED_NETWORKS
#
# Routes:
#   GET  /admin/              → dashboard overview
#   GET  /admin/users         → user management table
#   POST /admin/users/create  → create a new user
#   POST /admin/users/{id}/activate
#   POST /admin/users/{id}/deactivate
#   POST /admin/users/{id}/promote
#   POST /admin/users/{id}/demote
#   POST /admin/users/{id}/reset-password
#   GET  /admin/sessions      → session list
#   POST /admin/sessions/{user_id}/expire
#   GET  /admin/conversations → conversation browser

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import hash_password, require_admin
from db import (
    create_user,
    expire_all_user_sessions,
    get_conversation_detail,
    get_user_by_email,
    get_user_by_username,
    list_conversations_admin,
    list_sessions,
    list_users,
    set_user_active,
    set_user_admin,
    set_user_password,
)

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)

router = APIRouter(prefix="/admin")


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, admin: dict = Depends(require_admin)):
    users = list_users()
    all_sessions = list_sessions(limit=200)
    recent_convs = list_conversations_admin(limit=10)

    active_sessions = sum(1 for s in all_sessions if s["is_active"])
    total_users     = len(users)
    active_users    = sum(1 for u in users if u["is_active"])

    return templates.TemplateResponse("admin/dashboard.html", {
        "request":          request,
        "admin":            admin,
        "total_users":      total_users,
        "active_users":     active_users,
        "active_sessions":  active_sessions,
        "recent_convs":     recent_convs,
    })


# ─────────────────────────────────────────────
# USER MANAGEMENT
# ─────────────────────────────────────────────

@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    admin: dict = Depends(require_admin),
    msg: str = None,
    error: str = None,
):
    users = list_users()
    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "admin":   admin,
        "users":   users,
        "msg":     msg,
        "error":   error,
    })


@router.post("/users/create")
async def create_user_admin(
    request: Request,
    username: str  = Form(...),
    email:    str  = Form(...),
    password: str  = Form(...),
    is_admin: bool = Form(default=False),
    admin: dict    = Depends(require_admin),
):
    if get_user_by_username(username):
        return RedirectResponse(
            url="/admin/users?error=Username+already+exists", status_code=302
        )
    if get_user_by_email(email):
        return RedirectResponse(
            url="/admin/users?error=Email+already+registered", status_code=302
        )
    if len(password) < 8:
        return RedirectResponse(
            url="/admin/users?error=Password+must+be+at+least+8+characters", status_code=302
        )

    user_id = create_user(username, email, hash_password(password))
    if is_admin:
        set_user_admin(user_id, True)

    return RedirectResponse(
        url=f"/admin/users?msg=User+{username}+created", status_code=302
    )


@router.post("/users/{user_id}/activate")
async def activate_user(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_admin),
):
    set_user_active(user_id, True)
    return RedirectResponse(url="/admin/users?msg=User+activated", status_code=302)


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_admin),
):
    set_user_active(user_id, False)
    expire_all_user_sessions(user_id)
    return RedirectResponse(url="/admin/users?msg=User+deactivated", status_code=302)


@router.post("/users/{user_id}/promote")
async def promote_user(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_admin),
):
    set_user_admin(user_id, True)
    return RedirectResponse(url="/admin/users?msg=User+promoted+to+admin", status_code=302)


@router.post("/users/{user_id}/demote")
async def demote_user(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_admin),
):
    set_user_admin(user_id, False)
    return RedirectResponse(url="/admin/users?msg=Admin+role+removed", status_code=302)


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id:      str,
    request:      Request,
    new_password: str = Form(...),
    admin: dict       = Depends(require_admin),
):
    if len(new_password) < 8:
        return RedirectResponse(
            url="/admin/users?error=Password+must+be+at+least+8+characters",
            status_code=302,
        )
    set_user_password(user_id, hash_password(new_password))
    expire_all_user_sessions(user_id)
    return RedirectResponse(
        url="/admin/users?msg=Password+reset+and+sessions+expired", status_code=302
    )


# ─────────────────────────────────────────────
# SESSIONS
# ─────────────────────────────────────────────

@router.get("/sessions", response_class=HTMLResponse)
async def admin_sessions(request: Request, admin: dict = Depends(require_admin)):
    sessions = list_sessions(limit=200)
    return templates.TemplateResponse("admin/sessions.html", {
        "request":  request,
        "admin":    admin,
        "sessions": sessions,
    })


@router.post("/sessions/{user_id}/expire")
async def expire_sessions(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_admin),
):
    expire_all_user_sessions(user_id)
    return RedirectResponse(
        url="/admin/sessions?msg=Sessions+expired", status_code=302
    )


# ─────────────────────────────────────────────
# CONVERSATIONS
# ─────────────────────────────────────────────

@router.get("/conversations", response_class=HTMLResponse)
async def admin_conversations(request: Request, admin: dict = Depends(require_admin)):
    conversations = list_conversations_admin(limit=200)
    return templates.TemplateResponse("admin/conversations.html", {
        "request":       request,
        "admin":         admin,
        "conversations": conversations,
    })


@router.get("/conversations/{conversation_id}", response_class=HTMLResponse)
async def admin_conversation_detail(
    conversation_id: str,
    request: Request,
    admin: dict = Depends(require_admin),
):
    detail = get_conversation_detail(conversation_id)
    if not detail:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")
    return templates.TemplateResponse("admin/conversation_detail.html", {
        "request": request,
        "admin":   admin,
        "c":       detail,
    })
