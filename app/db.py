# db.py
# Project 03 — Touchgrass Conversational Agent
#
# Handles all reads and writes to the app3 schema in urbandb.
# The scoring engine (score_engine.py) reads from the public schema.
# This file reads and writes to app3 — conversations, messages,
# results, and signals.
#
# Public functions:
#   create_conversation()           → creates new conversation, returns id
#   save_message(...)               → appends a message to a conversation
#   get_messages(conversation_id)   → retrieves full message history
#   save_results(...)               → saves derived weights + top cities
#   get_latest_results(...)         → retrieves most recent results
#   close_conversation(...)         → marks complete, records final counts
#   save_signals(...)               → saves ML training signals
#   touch_conversation(...)         → updates last_active_at
#   conversation_exists(...)        → checks if a conversation id is valid

import os
import json
import uuid
from typing import Optional

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()


# ─────────────────────────────────────────────
# ENGINE
# Reuses same DB as project-01 and project-02.
# App data lives in app3 schema, city data in public.
# ─────────────────────────────────────────────

def get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT', 5432)}/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)


# ─────────────────────────────────────────────
# CONVERSATION MANAGEMENT
# ─────────────────────────────────────────────

def create_conversation() -> str:
    """
    Creates a new conversation row and returns the UUID as a string.
    Called when a user loads the chat page and a session begins.
    """
    conversation_id = str(uuid.uuid4())
    query = text("""
        INSERT INTO app3.conversations (id)
        VALUES (:id)
    """)
    with get_engine().begin() as conn:
        conn.execute(query, {"id": conversation_id})
    return conversation_id


def conversation_exists(conversation_id: str) -> bool:
    """Returns True if a conversation with this UUID exists."""
    query = text("""
        SELECT 1 FROM app3.conversations WHERE id = :id
    """)
    with get_engine().connect() as conn:
        result = conn.execute(query, {"id": conversation_id}).fetchone()
    return result is not None


def touch_conversation(conversation_id: str) -> None:
    """Updates last_active_at to now. Called on every user message."""
    query = text("""
        UPDATE app3.conversations
        SET last_active_at = NOW()
        WHERE id = :id
    """)
    with get_engine().begin() as conn:
        conn.execute(query, {"id": conversation_id})


def close_conversation(
    conversation_id: str,
    turn_count: int,
    query_count: int
) -> None:
    """
    Marks a conversation as completed and records final counts.
    Called when the conversation ends naturally or hits the turn limit.
    """
    query = text("""
        UPDATE app3.conversations
        SET
            completed      = TRUE,
            last_active_at = NOW(),
            turn_count     = :turn_count,
            query_count    = :query_count
        WHERE id = :id
    """)
    with get_engine().begin() as conn:
        conn.execute(query, {
            "id":          conversation_id,
            "turn_count":  turn_count,
            "query_count": query_count,
        })


# ─────────────────────────────────────────────
# MESSAGE HISTORY
# ─────────────────────────────────────────────

def save_message(
    conversation_id: str,
    role: str,
    content: str,
    turn_number: Optional[int] = None
) -> None:
    """
    Appends a single message to the conversation history.

    Args:
        conversation_id: UUID from create_conversation()
        role:            'user' or 'assistant'
        content:         Raw message text. For assistant messages,
                         <state> tags must be stripped before calling.
        turn_number:     Optional turn index for ordering
    """
    if role not in ("user", "assistant"):
        raise ValueError(f"role must be 'user' or 'assistant', got '{role}'")

    query = text("""
        INSERT INTO app3.messages
            (conversation_id, role, content, turn_number)
        VALUES
            (:conversation_id, :role, :content, :turn_number)
    """)
    with get_engine().begin() as conn:
        conn.execute(query, {
            "conversation_id": conversation_id,
            "role":            role,
            "content":         content,
            "turn_number":     turn_number,
        })
    touch_conversation(conversation_id)


def get_messages(conversation_id: str) -> list:
    """
    Returns the full message history for a conversation in
    chronological order.

    Returns list of {"role": str, "content": str} dicts —
    exactly the format the Anthropic API expects in `messages`.
    The state tags are already stripped since they're stripped
    before save_message() is called for assistant turns.
    """
    query = text("""
        SELECT role, content
        FROM app3.messages
        WHERE conversation_id = :id
        ORDER BY created_at ASC, id ASC
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(query, {"id": conversation_id}).fetchall()

    return [{"role": row.role, "content": row.content} for row in rows]


# ─────────────────────────────────────────────
# RESULTS LOGGING
# ─────────────────────────────────────────────

def save_results(
    conversation_id: str,
    derived_weights: dict,
    top_cities: list,
    filters_applied: Optional[dict] = None,
    query_number: int = 1
) -> int:
    """
    Saves a query_cities result for a conversation.
    Called every time the LLM triggers a query_cities tool call.
    Up to 5 results rows per conversation.

    Args:
        conversation_id: UUID from create_conversation()
        derived_weights: 16-key dict summing to 1.0
        top_cities:      Ranked list from score_engine.score_cities()
        filters_applied: Geographic filter dict if any was used
        query_number:    1-5, incremented per query in the conversation

    Returns the new results row id.
    """
    weight_sum = round(sum(derived_weights.values()), 4)

    query = text("""
        INSERT INTO app3.conversation_results
            (conversation_id, query_number, derived_weights,
             filters_applied, top_cities, weight_sum)
        VALUES
            (:conversation_id, :query_number, :derived_weights,
             :filters_applied, :top_cities, :weight_sum)
        RETURNING id
    """)
    with get_engine().begin() as conn:
        result = conn.execute(query, {
            "conversation_id": conversation_id,
            "query_number":    query_number,
            "derived_weights": json.dumps(derived_weights),
            "filters_applied": json.dumps(filters_applied) if filters_applied else None,
            "top_cities":      json.dumps(top_cities),
            "weight_sum":      weight_sum,
        })
        row_id = result.fetchone()[0]

    return row_id


def get_latest_results(conversation_id: str) -> Optional[dict]:
    """
    Returns the most recent query_cities result for a conversation.
    Used when the frontend needs to re-render results after a reload.
    """
    query = text("""
        SELECT
            id, conversation_id, created_at, query_number,
            derived_weights, filters_applied, top_cities, weight_sum
        FROM app3.conversation_results
        WHERE conversation_id = :id
        ORDER BY created_at DESC
        LIMIT 1
    """)
    with get_engine().connect() as conn:
        row = conn.execute(query, {"id": conversation_id}).fetchone()

    if row is None:
        return None

    return {
        "id":              row.id,
        "conversation_id": str(row.conversation_id),
        "created_at":      row.created_at.isoformat(),
        "query_number":    row.query_number,
        "derived_weights": row.derived_weights,
        "filters_applied": row.filters_applied,
        "top_cities":      row.top_cities,
        "weight_sum":      float(row.weight_sum) if row.weight_sum else None,
    }


# ─────────────────────────────────────────────
# SIGNAL LOGGING
# Written async at conversation close.
# Powers the ML training dataset.
# ─────────────────────────────────────────────

def save_signals(
    conversation_id: str,
    final_weight_vector: dict,
    named_cities: Optional[list] = None,
    named_states: Optional[list] = None,
    budget_mentioned: bool = False,
    remote_work: bool = False,
    has_kids: bool = False,
    turn_count: int = 0,
    raw_signal_notes: Optional[str] = None
) -> None:
    """
    Saves extracted conversation signals for the ML training dataset.
    Called once at conversation close.

    Each row is a labeled training example:
    (conversation_context → derived_weight_vector)
    """
    query = text("""
        INSERT INTO app3.conversation_signals
            (conversation_id, final_weight_vector, named_cities,
             named_states, budget_mentioned, remote_work,
             has_kids, turn_count, raw_signal_notes)
        VALUES
            (:conversation_id, :final_weight_vector, :named_cities,
             :named_states, :budget_mentioned, :remote_work,
             :has_kids, :turn_count, :raw_signal_notes)
    """)
    with get_engine().begin() as conn:
        conn.execute(query, {
            "conversation_id":     conversation_id,
            "final_weight_vector": json.dumps(final_weight_vector),
            "named_cities":        named_cities or [],
            "named_states":        named_states or [],
            "budget_mentioned":    budget_mentioned,
            "remote_work":         remote_work,
            "has_kids":            has_kids,
            "turn_count":          turn_count,
            "raw_signal_notes":    raw_signal_notes,
        })


# ─────────────────────────────────────────────
# AUTH — USERS
# ─────────────────────────────────────────────

def create_user(username: str, email: str, password_hash: str) -> str:
    """Creates a new user row and returns the UUID string."""
    query = text("""
        INSERT INTO app3.users (username, email, password_hash)
        VALUES (:username, :email, :password_hash)
        RETURNING id
    """)
    with get_engine().begin() as conn:
        result = conn.execute(query, {
            "username":      username,
            "email":         email,
            "password_hash": password_hash,
        })
        return str(result.fetchone()[0])


def get_user_by_username(username: str) -> Optional[dict]:
    query = text("""
        SELECT id, username, email, password_hash, is_admin, is_active,
               created_at, last_login_at
        FROM app3.users WHERE username = :username
    """)
    with get_engine().connect() as conn:
        row = conn.execute(query, {"username": username}).fetchone()
    if row is None:
        return None
    return {
        "id":            str(row.id),
        "username":      row.username,
        "email":         row.email,
        "password_hash": row.password_hash,
        "is_admin":      row.is_admin,
        "is_active":     row.is_active,
        "created_at":    row.created_at.isoformat() if row.created_at else None,
        "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
    }


def get_user_by_email(email: str) -> Optional[dict]:
    query = text("""
        SELECT id, username, email, password_hash, is_admin, is_active
        FROM app3.users WHERE email = :email
    """)
    with get_engine().connect() as conn:
        row = conn.execute(query, {"email": email}).fetchone()
    if row is None:
        return None
    return {
        "id":            str(row.id),
        "username":      row.username,
        "email":         row.email,
        "password_hash": row.password_hash,
        "is_admin":      row.is_admin,
        "is_active":     row.is_active,
    }


def update_last_login(user_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE app3.users SET last_login_at = NOW() WHERE id = :id
        """), {"id": user_id})


def set_user_active(user_id: str, is_active: bool) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE app3.users SET is_active = :active WHERE id = :id
        """), {"id": user_id, "active": is_active})


def set_user_admin(user_id: str, is_admin: bool) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE app3.users SET is_admin = :admin WHERE id = :id
        """), {"id": user_id, "admin": is_admin})


def set_user_password(user_id: str, password_hash: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE app3.users SET password_hash = :hash WHERE id = :id
        """), {"id": user_id, "hash": password_hash})


# ─────────────────────────────────────────────
# AUTH — SESSIONS (admin queries)
# ─────────────────────────────────────────────

def list_users() -> list:
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT id, username, email, is_admin, is_active, created_at, last_login_at
            FROM app3.users ORDER BY created_at DESC
        """)).fetchall()
    return [{
        "id":            str(r.id),
        "username":      r.username,
        "email":         r.email,
        "is_admin":      r.is_admin,
        "is_active":     r.is_active,
        "created_at":    r.created_at.isoformat() if r.created_at else None,
        "last_login_at": r.last_login_at.isoformat() if r.last_login_at else None,
    } for r in rows]


def list_sessions(limit: int = 200) -> list:
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT s.session_token, s.user_id, u.username,
                   s.created_at, s.expires_at, s.ip_address,
                   s.user_agent, s.is_active
            FROM app3.user_sessions s
            JOIN app3.users u ON u.id = s.user_id
            ORDER BY s.created_at DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
    return [{
        "session_token": r.session_token[:12] + "…",  # truncated for display
        "user_id":       str(r.user_id),
        "username":      r.username,
        "created_at":    r.created_at.isoformat() if r.created_at else None,
        "expires_at":    r.expires_at.isoformat() if r.expires_at else None,
        "ip_address":    r.ip_address,
        "user_agent":    (r.user_agent or "")[:80],
        "is_active":     r.is_active,
    } for r in rows]


def expire_all_user_sessions(user_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE app3.user_sessions SET is_active = FALSE WHERE user_id = :id
        """), {"id": user_id})


def get_conversation_detail(conversation_id: str) -> Optional[dict]:
    """
    Returns full detail for a single conversation:
    metadata, all messages, all result snapshots, and signals if present.
    Used by the admin conversation detail view.
    """
    with get_engine().connect() as conn:
        # Metadata + user
        meta = conn.execute(text("""
            SELECT c.id, c.created_at, c.last_active_at, c.completed,
                   c.turn_count, c.query_count, c.user_id, u.username
            FROM app3.conversations c
            LEFT JOIN app3.users u ON u.id = c.user_id
            WHERE c.id = :id
        """), {"id": conversation_id}).fetchone()

        if meta is None:
            return None

        # All messages in order
        messages = conn.execute(text("""
            SELECT role, content, turn_number, created_at
            FROM app3.messages
            WHERE conversation_id = :id
            ORDER BY created_at ASC, id ASC
        """), {"id": conversation_id}).fetchall()

        # All result snapshots
        results = conn.execute(text("""
            SELECT id, query_number, derived_weights, top_cities,
                   filters_applied, weight_sum, created_at
            FROM app3.conversation_results
            WHERE conversation_id = :id
            ORDER BY query_number ASC
        """), {"id": conversation_id}).fetchall()

        # Signals (if logged)
        signals = conn.execute(text("""
            SELECT final_weight_vector, named_cities, named_states,
                   budget_mentioned, remote_work, has_kids,
                   turn_count, raw_signal_notes, created_at
            FROM app3.conversation_signals
            WHERE conversation_id = :id
            LIMIT 1
        """), {"id": conversation_id}).fetchone()

    return {
        "id":             str(meta.id),
        "created_at":     meta.created_at.isoformat() if meta.created_at else None,
        "last_active_at": meta.last_active_at.isoformat() if meta.last_active_at else None,
        "completed":      meta.completed,
        "turn_count":     meta.turn_count,
        "query_count":    meta.query_count,
        "user_id":        str(meta.user_id) if meta.user_id else None,
        "username":       meta.username,
        "messages": [{
            "role":         r.role,
            "content":      r.content,
            "turn_number":  r.turn_number,
            "created_at":   r.created_at.isoformat() if r.created_at else None,
            "is_tool":      r.content.startswith("[TOOL RESULTS]"),
        } for r in messages],
        "results": [{
            "query_number":    r.query_number,
            "top_cities":      r.top_cities,
            "derived_weights": r.derived_weights,
            "weight_sum":      float(r.weight_sum) if r.weight_sum else None,
            "created_at":      r.created_at.isoformat() if r.created_at else None,
        } for r in results],
        "signals": {
            "final_weight_vector": signals.final_weight_vector,
            "named_cities":        signals.named_cities,
            "named_states":        signals.named_states,
            "budget_mentioned":    signals.budget_mentioned,
            "remote_work":         signals.remote_work,
            "has_kids":            signals.has_kids,
            "turn_count":          signals.turn_count,
            "raw_signal_notes":    signals.raw_signal_notes,
        } if signals else None,
    }


def list_conversations_admin(limit: int = 200) -> list:
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT c.id, c.created_at, c.last_active_at, c.completed,
                   c.turn_count, c.query_count, c.user_id, u.username
            FROM app3.conversations c
            LEFT JOIN app3.users u ON u.id = c.user_id
            ORDER BY c.created_at DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
    return [{
        "id":             str(r.id),
        "created_at":     r.created_at.isoformat() if r.created_at else None,
        "last_active_at": r.last_active_at.isoformat() if r.last_active_at else None,
        "completed":      r.completed,
        "turn_count":     r.turn_count,
        "query_count":    r.query_count,
        "user_id":        str(r.user_id) if r.user_id else None,
        "username":       r.username,
    } for r in rows]


def get_user_conversations(user_id: str, limit: int = 30) -> list:
    """
    Returns a user's conversation history, newest first.
    Each row includes the top 3 cities from the most recent query result.
    """
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT c.id, c.created_at, c.turn_count, c.query_count, c.completed,
                   cr.top_cities
            FROM app3.conversations c
            LEFT JOIN LATERAL (
                SELECT top_cities
                FROM app3.conversation_results
                WHERE conversation_id = c.id
                ORDER BY created_at DESC
                LIMIT 1
            ) cr ON true
            WHERE c.user_id = :user_id
            ORDER BY c.created_at DESC
            LIMIT :limit
        """), {"user_id": user_id, "limit": limit}).fetchall()
    return [{
        "id":          str(r.id),
        "created_at":  r.created_at.isoformat() if r.created_at else None,
        "turn_count":  r.turn_count or 0,
        "query_count": r.query_count or 0,
        "completed":   r.completed,
        "top_cities":  r.top_cities[:3] if r.top_cities else [],
    } for r in rows]


def create_conversation_for_user(user_id: Optional[str] = None) -> str:
    """
    Creates a new conversation row linked to a user (if provided).
    Replaces create_conversation() for authenticated requests.
    """
    conversation_id = str(uuid.uuid4())
    query = text("""
        INSERT INTO app3.conversations (id, user_id)
        VALUES (:id, :user_id)
    """)
    with get_engine().begin() as conn:
        conn.execute(query, {"id": conversation_id, "user_id": user_id})
    return conversation_id


# ─────────────────────────────────────────────
# SMOKE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("Running db.py smoke test...")
    print("─" * 50)

    # 1. Create conversation
    cid = create_conversation()
    print(f"✓ Created conversation: {cid}")

    # 2. Confirm exists
    assert conversation_exists(cid), "Conversation not found after creation"
    print(f"✓ Conversation exists: True")

    # 3. Save messages
    save_message(cid, "user", "I want to move somewhere cheaper.", turn_number=1)
    save_message(cid, "assistant", "Tell me more — what does cheap mean to you?", turn_number=1)
    save_message(cid, "user", "I'm paying 50% of my income on rent right now.", turn_number=2)
    print(f"✓ Saved 3 messages")

    # 4. Retrieve history
    messages = get_messages(cid)
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    print(f"✓ Retrieved {len(messages)} messages in correct order")

    # 5. Save results
    mock_weights = {
        "econ_wealth": 0.03, "econ_affordability": 0.20, "econ_housing": 0.15,
        "econ_inequality": 0.05, "lifestyle_food": 0.05, "lifestyle_arts": 0.04,
        "lifestyle_outdoor": 0.06, "community_capital": 0.04, "community_civic": 0.04,
        "community_equity": 0.04, "mobility_commute": 0.06, "mobility_transit": 0.08,
        "mobility_housing": 0.04, "health_air": 0.04, "health_access": 0.04,
        "health_outcomes": 0.04,
    }
    mock_cities = [
        {"rank": 1, "name": "Minneapolis, MN", "state": "MN-WI",
         "personalized_score": 100.0},
        {"rank": 2, "name": "Portland, OR", "state": "OR-WA",
         "personalized_score": 91.4},
    ]
    result_id = save_results(
        conversation_id=cid,
        derived_weights=mock_weights,
        top_cities=mock_cities,
        query_number=1
    )
    print(f"✓ Saved results, row id: {result_id}")

    # 6. Retrieve latest results
    results = get_latest_results(cid)
    assert results is not None
    assert results["top_cities"][0]["name"] == "Minneapolis, MN"
    print(f"✓ Retrieved results, top city: {results['top_cities'][0]['name']}")

    # 7. Save signals
    save_signals(
        conversation_id=cid,
        final_weight_vector=mock_weights,
        named_cities=["New York"],
        budget_mentioned=True,
        turn_count=2
    )
    print(f"✓ Saved signals")

    # 8. Close conversation
    close_conversation(cid, turn_count=2, query_count=1)
    print(f"✓ Closed conversation")

    print("─" * 50)
    print("All checks passed.")
