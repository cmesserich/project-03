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
