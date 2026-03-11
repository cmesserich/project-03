# logger.py
# Project 03 — Touchgrass Conversational Agent
#
# Async background logging for conversation close events.
# Fires off DB writes in a daemon thread so app.py never
# blocks waiting on them.
#
# Two jobs at conversation close:
#   1. save_signals() — extract and persist ML training signals
#   2. close_conversation() — mark completed, record final counts
#
# PUBLIC API
# ───────────
#   log_conversation_close(manager, conversation_id)
#       → fires background thread, returns immediately
#
#   extract_signals(manager)
#       → pure function, returns signal dict from ConversationManager
#         (testable without DB)

import threading
from typing import Optional
from conversation import ConversationManager


# ─────────────────────────────────────────────
# SIGNAL EXTRACTION
# Pure function — no DB, no side effects.
# Pulls structured signals out of the conversation
# for the ML training dataset.
# ─────────────────────────────────────────────

def extract_signals(manager: ConversationManager) -> dict:
    """
    Extracts structured signals from a completed ConversationManager.
    Returns a dict ready to pass directly to db.save_signals().

    Signals extracted:
      - final_weight_vector   from latest LLM state
      - named_cities          city names mentioned in user messages
      - named_states          state names/abbrs mentioned in user messages
      - budget_mentioned      any cost/rent/afford language in user messages
      - remote_work           any remote work language in user messages
      - has_kids              any kids/children/school language in user messages
      - turn_count            how many turns the conversation ran

    This is intentionally simple for MVP — signal extraction will
    get more sophisticated as the dataset grows.
    """
    weights = manager.get_derived_weights() or {}
    user_text = " ".join(
        m["content"].lower()
        for m in manager.get_clean_messages()
        if m["role"] == "user"
    )

    # City name detection — scan for known city names in user messages
    # Uses a small hardcoded list of the most commonly mentioned cities.
    # Will expand as we see real conversation data.
    CITY_SIGNALS = [
        "new york", "los angeles", "chicago", "houston", "phoenix",
        "philadelphia", "san antonio", "san diego", "dallas", "san jose",
        "seattle", "denver", "boston", "portland", "minneapolis",
        "washington", "atlanta", "miami", "nashville", "raleigh",
        "austin", "charlotte", "columbus", "indianapolis", "detroit",
        "memphis", "baltimore", "milwaukee", "albuquerque", "tucson",
        "fresno", "sacramento", "kansas city", "omaha", "cleveland",
        "pittsburgh", "cincinnati", "st. louis", "tampa", "orlando",
    ]
    named_cities = [c for c in CITY_SIGNALS if c in user_text]

    # State detection — both full names and abbreviations
    STATE_SIGNALS = [
        "california", "texas", "florida", "new york", "illinois",
        "pennsylvania", "ohio", "georgia", "north carolina", "michigan",
        "washington", "arizona", "massachusetts", "tennessee", "indiana",
        "missouri", "maryland", "wisconsin", "colorado", "minnesota",
        "south carolina", "alabama", "louisiana", "kentucky", "oregon",
        "connecticut", "iowa", "mississippi", "arkansas", "utah",
        "nevada", "kansas", "new mexico", "nebraska", "west virginia",
        "idaho", "hawaii", "new hampshire", "maine", "montana",
        "rhode island", "delaware", "south dakota", "north dakota",
        "alaska", "vermont", "wyoming", "dc", "pacific northwest",
        "midwest", "southeast", "southwest", "northeast", "west coast",
        "east coast", "sunbelt", "rust belt",
    ]
    named_states = [s for s in STATE_SIGNALS if s in user_text]

    # Boolean signal flags
    BUDGET_TERMS = [
        "rent", "afford", "cheap", "cost", "expensive", "mortgage",
        "income", "salary", "budget", "price", "housing cost",
    ]
    REMOTE_TERMS = [
        "remote", "work from home", "wfh", "work remotely",
        "telecommute", "distributed", "fully remote",
    ]
    KIDS_TERMS = [
        "kids", "children", "child", "school", "elementary",
        "middle school", "high school", "family", "raising",
    ]

    budget_mentioned = any(t in user_text for t in BUDGET_TERMS)
    remote_work      = any(t in user_text for t in REMOTE_TERMS)
    has_kids         = any(t in user_text for t in KIDS_TERMS)

    return {
        "final_weight_vector": weights,
        "named_cities":        named_cities,
        "named_states":        named_states,
        "budget_mentioned":    budget_mentioned,
        "remote_work":         remote_work,
        "has_kids":            has_kids,
        "turn_count":          manager.turn,
    }


# ─────────────────────────────────────────────
# BACKGROUND LOGGER
# Fires DB writes in a daemon thread.
# Returns immediately — never blocks app.py.
# ─────────────────────────────────────────────

def _log_worker(
    conversation_id: str,
    signals: dict,
    turn_count: int,
    query_count: int
) -> None:
    """
    Worker function executed in a background thread.
    Writes signals and closes the conversation row.
    Errors are caught and printed — never raised to caller.
    """
    try:
        from db import save_signals, close_conversation
        save_signals(conversation_id=conversation_id, **signals)
        close_conversation(
            conversation_id=conversation_id,
            turn_count=turn_count,
            query_count=query_count,
        )
    except Exception as e:
        # Background thread — can't raise to caller.
        # Log to stdout for now; wire to a real logger in v2.
        print(f"[logger] ERROR closing conversation {conversation_id}: {e}")


def log_conversation_close(
    manager: ConversationManager,
    conversation_id: Optional[str] = None
) -> None:
    """
    Extracts signals from the manager and fires background DB writes.
    Returns immediately — DB writes happen in a daemon thread.

    Args:
        manager:         Completed ConversationManager instance
        conversation_id: Optional override. Uses manager.conversation_id
                         if not provided.

    Usage in app.py:
        log_conversation_close(manager)
        return JSONResponse({"status": "done"})  # returns before DB writes finish
    """
    cid = conversation_id or manager.conversation_id
    signals = extract_signals(manager)

    thread = threading.Thread(
        target=_log_worker,
        args=(cid, signals, manager.turn, manager.query_count),
        daemon=True,  # won't block process shutdown
    )
    thread.start()


# ─────────────────────────────────────────────
# SMOKE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import time
    print("Running logger.py smoke test...")
    print("─" * 50)

    mock_response = """
Thanks for sharing that — sounds like affordability and outdoor
access are your two biggest priorities.

<state>
{
  "turn": 3,
  "derived_weights": {
    "econ_wealth": 0.03, "econ_affordability": 0.20,
    "econ_housing": 0.15, "econ_inequality": 0.05,
    "lifestyle_food": 0.05, "lifestyle_arts": 0.04,
    "lifestyle_outdoor": 0.14, "community_capital": 0.04,
    "community_civic": 0.04, "community_equity": 0.04,
    "mobility_commute": 0.06, "mobility_transit": 0.06,
    "mobility_housing": 0.04, "health_air": 0.02,
    "health_access": 0.02, "health_outcomes": 0.02
  },
  "filters": {"states": [], "exclude_states": []},
  "ready_to_query": true,
  "query_count": 1,
  "tools_to_call": []
}
</state>

Ready to show you some results.
""".strip()

    # Build a mock conversation
    from conversation import ConversationManager
    manager = ConversationManager("test-logger-001")
    manager.add_user_message(
        "I'm paying 55% of my income on rent in New York. "
        "I work remotely and have two kids in school. "
        "I love hiking and trails. Thinking about the Pacific Northwest or Colorado."
    )
    manager.add_assistant_message(mock_response)
    manager.add_user_message("I'm open to Seattle or Portland or Denver area.")

    # 1. extract_signals — pure function test
    signals = extract_signals(manager)
    assert signals["budget_mentioned"] == True
    assert signals["remote_work"] == True
    assert signals["has_kids"] == True
    assert signals["turn_count"] == 2
    assert "new york" in signals["named_cities"]
    assert "pacific northwest" in signals["named_states"]
    assert "colorado" in signals["named_states"]
    assert len(signals["final_weight_vector"]) == 16
    print(f"✓ extract_signals:")
    print(f"   budget={signals['budget_mentioned']}, "
          f"remote={signals['remote_work']}, "
          f"kids={signals['has_kids']}")
    print(f"   cities={signals['named_cities']}")
    print(f"   states={signals['named_states']}")
    print(f"   turns={signals['turn_count']}, weights={len(signals['final_weight_vector'])} keys")

    # 2. log_conversation_close — fires background thread against live DB
    from db import create_conversation
    live_cid = create_conversation()
    print(f"\n✓ Created test conversation: {live_cid}")

    log_conversation_close(manager, conversation_id=live_cid)
    print(f"✓ log_conversation_close: returned immediately (non-blocking)")

    # Give the background thread time to finish
    time.sleep(1.0)

    # Verify the DB writes completed
    from db import get_latest_results
    from sqlalchemy import create_engine, text
    import os
    from dotenv import load_dotenv
    load_dotenv()

    engine = create_engine(
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT', 5432)}/{os.getenv('DB_NAME')}"
    )
    with engine.connect() as conn:
        conv = conn.execute(text("""
            SELECT completed, turn_count, query_count
            FROM app3.conversations WHERE id = :id
        """), {"id": live_cid}).fetchone()
        sig = conn.execute(text("""
            SELECT budget_mentioned, remote_work, has_kids, turn_count
            FROM app3.conversation_signals WHERE conversation_id = :id
        """), {"id": live_cid}).fetchone()

    assert conv is not None
    assert conv.completed == True
    assert conv.turn_count == 2
    print(f"✓ DB: conversation closed, completed=True, turn_count={conv.turn_count}")

    assert sig is not None
    assert sig.budget_mentioned == True
    assert sig.remote_work == True
    assert sig.has_kids == True
    print(f"✓ DB: signals saved, budget={sig.budget_mentioned}, "
          f"remote={sig.remote_work}, kids={sig.has_kids}")

    print("─" * 50)
    print("All checks passed.")