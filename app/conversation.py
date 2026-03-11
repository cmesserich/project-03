# conversation.py
# Project 03 — Touchgrass Conversational Agent
#
# Manages conversation state, message history, and the boundary
# between what the LLM sees and what the client/DB sees.
#
# THE CORE PROBLEM THIS SOLVES
# ─────────────────────────────
# The LLM appends a <state> JSON block to every response.
# That block carries derived weights, tool calls, turn count, etc.
#
#   - The LLM MUST see its own <state> tags in history (continuity)
#   - The client must NEVER see <state> tags (clean UX)
#   - The DB must NEVER store <state> tags (clean data)
#
# So we maintain two message lists per conversation:
#   raw_messages   — full text including <state> tags → Anthropic API
#   clean_messages — state stripped                   → client + DB
#
# BUILD STAGES
# ─────────────
# Stage 1: State parser and stripper — pure functions
# Stage 2: ConversationManager class — message history
# Stage 3: DB integration — persist and load via db.py

import re
import json
from copy import deepcopy
from typing import Optional


# ─────────────────────────────────────────────
# STAGE 1 — STATE PARSER AND STRIPPER
#
# Pure functions. No DB, no API calls.
# Fully testable in isolation.
# ─────────────────────────────────────────────

# Matches <state>...</state> including whitespace and newlines
_STATE_PATTERN = re.compile(r'<state>\s*(.*?)\s*</state>', re.DOTALL)


def extract_state(text: str) -> Optional[dict]:
    """
    Extracts and parses the <state> JSON block from an LLM response.
    Returns the parsed dict, or None if no block is found or the
    JSON inside is malformed.

    Expected format in every LLM response:
        <state>
        {
          "turn": 2,
          "derived_weights": { ... },
          "ready_to_query": false,
          "tools_to_call": [],
          "query_count": 0,
          "filters": { "states": [], "exclude_states": [] }
        }
        </state>
    """
    match = _STATE_PATTERN.search(text)
    if not match:
        return None

    raw_json = match.group(1).strip()
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError:
        # Block found but JSON is malformed — return None.
        # app.py should treat this the same as a missing state block.
        return None


def strip_state(text: str) -> str:
    """
    Removes the <state>...</state> block from an LLM response.
    Returns clean text suitable for display to the user or storage
    in the DB. Trailing/leading whitespace cleaned up after removal.
    """
    return _STATE_PATTERN.sub('', text).strip()


# ── State field accessors ─────────────────────────────────────
# These accept a parsed state dict (or None) and return safe
# defaults if the key is missing or state is None entirely.

def get_turn(state: Optional[dict]) -> int:
    """Current turn number. 0 if state is None."""
    if state is None:
        return 0
    return int(state.get("turn", 0))


def get_derived_weights(state: Optional[dict]) -> Optional[dict]:
    """
    The 16-key weight vector. None if not present.
    Validation (sum to 1.0, all keys present) happens in
    score_engine.validate_weights() before any scoring call.
    """
    if state is None:
        return None
    return state.get("derived_weights")


def get_filters(state: Optional[dict]) -> Optional[dict]:
    """
    Geographic filter dict, or None if no filters are active.
    Format: {"states": [...], "exclude_states": [...]}
    Returns None if both lists are empty — cleaner downstream.
    """
    if state is None:
        return None
    filters = state.get("filters", {})
    if not filters:
        return None
    has_states = bool(filters.get("states"))
    has_excludes = bool(filters.get("exclude_states"))
    if not has_states and not has_excludes:
        return None
    return filters


def is_ready_to_query(state: Optional[dict]) -> bool:
    """True if the LLM has set ready_to_query to true."""
    if state is None:
        return False
    return bool(state.get("ready_to_query", False))


def get_tools_to_call(state: Optional[dict]) -> list:
    """
    List of tool names the LLM wants to call after this turn.
    Empty list if none. e.g. ["query_cities", "generate_chart"]
    """
    if state is None:
        return []
    return state.get("tools_to_call", [])


def get_query_count(state: Optional[dict]) -> int:
    """How many query_cities calls have been made so far. 0 if None."""
    if state is None:
        return 0
    return int(state.get("query_count", 0))


# ─────────────────────────────────────────────
# STAGE 2 — CONVERSATION MANAGER
#
# Maintains raw (with <state>) and clean (stripped)
# message lists in parallel. app.py imports this class
# and calls add_user_message / add_assistant_message
# on every turn.
# ─────────────────────────────────────────────

class ConversationManager:
    """
    Manages the full message history for one conversation.

    Two parallel lists are maintained:
      raw_messages   — includes <state> tags → sent to Anthropic API
      clean_messages — state stripped        → sent to client + saved to DB

    The LLM needs to see its own prior <state> blocks in history to
    maintain continuity across turns (weights, turn count, signals
    accumulate across the conversation). The client and DB never
    need to see them.

    Usage in app.py:
        manager = ConversationManager(conversation_id)
        manager.add_user_message(user_text)
        response = call_anthropic(manager.get_api_messages())
        manager.add_assistant_message(response)
        clean_text = manager.get_latest_clean_response()
        if manager.is_ready_to_query():
            weights = manager.get_derived_weights()
            filters = manager.get_filters()
            # → call score_engine.score_cities(weights, filters)
    """

    MAX_TURNS = 12
    MAX_QUERIES = 5

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.raw_messages: list = []
        self.clean_messages: list = []
        self.latest_state: Optional[dict] = None
        self.turn: int = 0
        self.query_count: int = 0

    def add_user_message(self, content: str) -> None:
        """
        Adds a user message to both lists.
        User messages never contain state tags so both lists
        receive identical content.
        """
        msg = {"role": "user", "content": content}
        self.raw_messages.append(deepcopy(msg))
        self.clean_messages.append(deepcopy(msg))
        self.turn += 1

    def add_assistant_message(self, content: str) -> None:
        """
        Adds an LLM response.
          - raw gets the full content including <state> tags
          - clean gets the stripped version
          - latest_state is updated from the parsed block
          - query_count synced from state
        """
        # Full content for the API — LLM sees its own prior state
        self.raw_messages.append({"role": "assistant", "content": content})

        # Parse state before stripping
        self.latest_state = extract_state(content)
        if self.latest_state:
            self.query_count = get_query_count(self.latest_state)

        # Stripped content for client + DB
        clean_content = strip_state(content)
        self.clean_messages.append({"role": "assistant", "content": clean_content})

    def get_api_messages(self) -> list:
        """
        Returns the full raw message history for the Anthropic API call.
        Includes <state> tags in assistant messages.
        Returns a deep copy so callers can't mutate internal state.
        """
        return deepcopy(self.raw_messages)

    def get_clean_messages(self) -> list:
        """
        Returns the clean message history (state stripped).
        Used for saving to DB and sending to the client.
        """
        return deepcopy(self.clean_messages)

    def get_latest_clean_response(self) -> Optional[str]:
        """
        The most recent assistant message with state stripped.
        Used to display the latest response to the user.
        """
        for msg in reversed(self.clean_messages):
            if msg["role"] == "assistant":
                return msg["content"]
        return None

    # ── State accessors (delegate to module-level functions) ──

    def is_ready_to_query(self) -> bool:
        return is_ready_to_query(self.latest_state)

    def get_tools_to_call(self) -> list:
        return get_tools_to_call(self.latest_state)

    def get_derived_weights(self) -> Optional[dict]:
        return get_derived_weights(self.latest_state)

    def get_filters(self) -> Optional[dict]:
        return get_filters(self.latest_state)

    # ── Limit checks ──────────────────────────────────────────

    def at_turn_limit(self) -> bool:
        """True if the conversation has reached MAX_TURNS."""
        return self.turn >= self.MAX_TURNS

    def at_query_limit(self) -> bool:
        """True if the conversation has reached MAX_QUERIES."""
        return self.query_count >= self.MAX_QUERIES

    def summary(self) -> dict:
        """Snapshot of current conversation state. Useful for logging."""
        return {
            "conversation_id": self.conversation_id,
            "turn":            self.turn,
            "query_count":     self.query_count,
            "message_count":   len(self.raw_messages),
            "ready_to_query":  self.is_ready_to_query(),
            "tools_to_call":   self.get_tools_to_call(),
            "has_weights":     self.get_derived_weights() is not None,
            "at_turn_limit":   self.at_turn_limit(),
            "at_query_limit":  self.at_query_limit(),
        }


# ─────────────────────────────────────────────
# STAGE 3 — DB INTEGRATION
#
# Two functions that wire ConversationManager to db.py.
# app.py only needs to import from conversation.py —
# it never calls db.py directly for message handling.
#
# NOTE ON THE RELOAD TRADEOFF
# ─────────────────────────────
# The DB stores clean messages (state stripped).
# If a user reloads mid-conversation, load_from_db()
# reconstructs the manager without <state> tags in history.
# The LLM will not see its prior weight accumulation.
# The system prompt handles this gracefully for MVP.
# Storing raw messages is a v2 improvement.
# ─────────────────────────────────────────────

def load_from_db(conversation_id: str) -> ConversationManager:
    """
    Reconstructs a ConversationManager from stored message history.
    Used when resuming a conversation after a page reload.

    Because the DB only stores clean messages, the reconstructed
    manager will have no <state> tags in its raw_messages — the LLM
    won't see its prior state blocks. This is acceptable for MVP.
    """
    from db import get_messages  # local import avoids circular deps at module load

    manager = ConversationManager(conversation_id)
    messages = get_messages(conversation_id)

    for msg in messages:
        # Both raw and clean get the same clean content on reload.
        # The LLM will treat this as a fresh context.
        entry = {"role": msg["role"], "content": msg["content"]}
        manager.raw_messages.append(deepcopy(entry))
        manager.clean_messages.append(deepcopy(entry))
        if msg["role"] == "user":
            manager.turn += 1

    return manager


def persist_message(
    conversation_id: str,
    role: str,
    content: str,
    turn_number: int
) -> None:
    """
    Saves a single message to the DB with state tags stripped.
    Thin wrapper around db.save_message() — app.py calls this
    rather than importing db directly for message persistence.

    Always strips state before saving, even if the caller forgot to.
    """
    from db import save_message  # local import avoids circular deps

    clean_content = strip_state(content) if role == "assistant" else content
    save_message(
        conversation_id=conversation_id,
        role=role,
        content=clean_content,
        turn_number=turn_number,
    )


# ─────────────────────────────────────────────
# SMOKE TEST — Stages 1, 2, and 3
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("conversation.py — Stage 1 + 2 + 3 smoke test")
    print("─" * 50)

    # Realistic mock LLM response with a state block
    mock_response = """
That's really helpful — it sounds like keeping costs down is
the main priority, and you'd also love to be near trails.

<state>
{
  "turn": 2,
  "derived_weights": {
    "econ_wealth": 0.03,
    "econ_affordability": 0.20,
    "econ_housing": 0.15,
    "econ_inequality": 0.05,
    "lifestyle_food": 0.05,
    "lifestyle_arts": 0.04,
    "lifestyle_outdoor": 0.14,
    "community_capital": 0.04,
    "community_civic": 0.04,
    "community_equity": 0.04,
    "mobility_commute": 0.06,
    "mobility_transit": 0.06,
    "mobility_housing": 0.04,
    "health_air": 0.02,
    "health_access": 0.02,
    "health_outcomes": 0.02
  },
  "filters": {
    "states": [],
    "exclude_states": []
  },
  "ready_to_query": false,
  "query_count": 0,
  "tools_to_call": []
}
</state>

What part of the country are you thinking, or are you open?
""".strip()

    # 1. extract_state — happy path
    state = extract_state(mock_response)
    assert state is not None
    assert state["turn"] == 2
    assert state["ready_to_query"] == False
    assert "econ_affordability" in state["derived_weights"]
    print(f"✓ extract_state: turn={state['turn']}, ready={state['ready_to_query']}")

    # 2. strip_state — tags gone, visible text preserved
    clean = strip_state(mock_response)
    assert "<state>" not in clean
    assert "</state>" not in clean
    assert "That's really helpful" in clean
    assert "What part of the country" in clean
    print(f"✓ strip_state: state tags removed, visible text intact")

    # 3. Accessors — normal state
    assert get_turn(state) == 2
    assert is_ready_to_query(state) == False
    assert get_tools_to_call(state) == []
    assert get_derived_weights(state) is not None
    assert get_filters(state) is None   # empty lists → None
    assert get_query_count(state) == 0
    print(f"✓ Accessors: all return correct values on normal state")

    # 4. Accessors — None state (graceful defaults)
    assert get_turn(None) == 0
    assert is_ready_to_query(None) == False
    assert get_tools_to_call(None) == []
    assert get_derived_weights(None) is None
    assert get_filters(None) is None
    assert get_query_count(None) == 0
    print(f"✓ Accessors: all return safe defaults when state is None")

    # 5. ready_to_query = true with tools
    mock_ready = mock_response \
        .replace('"ready_to_query": false', '"ready_to_query": true') \
        .replace('"tools_to_call": []', '"tools_to_call": ["query_cities"]')
    state_ready = extract_state(mock_ready)
    assert is_ready_to_query(state_ready) == True
    assert "query_cities" in get_tools_to_call(state_ready)
    print(f"✓ ready_to_query=true, tools={get_tools_to_call(state_ready)}")

    # 6. State with geographic filters
    mock_filtered = mock_response.replace(
        '"states": []',
        '"states": ["WA", "OR", "CA"]'
    )
    state_filtered = extract_state(mock_filtered)
    filters = get_filters(state_filtered)
    assert filters is not None
    assert "WA" in filters["states"]
    print(f"✓ Filters: {filters}")

    # 7. Malformed JSON in state block → None
    bad_response = "Hello <state>{broken: json</state> world"
    assert extract_state(bad_response) is None
    print(f"✓ Malformed JSON in state block returns None gracefully")

    # 8. No state block → None
    assert extract_state("Just a normal message, no state.") is None
    print(f"✓ No state block returns None gracefully")

    # 9. strip_state on message with no state block — unchanged
    plain = "Just a plain message."
    assert strip_state(plain) == plain
    print(f"✓ strip_state on plain message returns it unchanged")

    print("─" * 50)
    print("Stage 1 complete.")
    print()

    # ── Stage 2: ConversationManager ──────────────────────────
    print("Stage 2: ConversationManager")
    print("─" * 50)

    manager = ConversationManager("test-conv-001")

    # 10. Add user message — increments turn, both lists updated
    manager.add_user_message("I want to move somewhere cheaper.")
    assert manager.turn == 1
    assert len(manager.raw_messages) == 1
    assert len(manager.clean_messages) == 1
    assert manager.raw_messages[0]["role"] == "user"
    print(f"✓ add_user_message: turn={manager.turn}, lists synced")

    # 11. Add assistant message — raw has tags, clean does not
    manager.add_assistant_message(mock_response)
    assert len(manager.raw_messages) == 2
    assert len(manager.clean_messages) == 2
    assert "<state>" in manager.raw_messages[1]["content"]
    assert "<state>" not in manager.clean_messages[1]["content"]
    print(f"✓ add_assistant_message: raw has <state>, clean does not")

    # 12. API messages include state tags for LLM continuity
    api_msgs = manager.get_api_messages()
    assert "<state>" in api_msgs[1]["content"]
    # Deep copy — mutating return value doesn't affect internal state
    api_msgs[1]["content"] = "tampered"
    assert "<state>" in manager.raw_messages[1]["content"]
    print(f"✓ get_api_messages: state present, returns deep copy")

    # 13. Clean messages have no state tags
    clean_msgs = manager.get_clean_messages()
    assert "<state>" not in clean_msgs[1]["content"]
    assert "That's really helpful" in clean_msgs[1]["content"]
    print(f"✓ get_clean_messages: state absent, visible text intact")

    # 14. Latest clean response
    latest = manager.get_latest_clean_response()
    assert latest is not None
    assert "<state>" not in latest
    assert "What part of the country" in latest
    print(f"✓ get_latest_clean_response: clean, correct content")

    # 15. State accessors via manager
    assert manager.latest_state is not None
    assert manager.is_ready_to_query() == False
    assert manager.get_derived_weights() is not None
    assert manager.get_tools_to_call() == []
    assert manager.get_filters() is None
    print(f"✓ State accessors via manager: all correct")

    # 16. ready_to_query triggers correctly
    manager2 = ConversationManager("test-conv-002")
    manager2.add_user_message("I need to move, I hate my commute.")
    ready_response = mock_response \
        .replace('"ready_to_query": false', '"ready_to_query": true') \
        .replace('"tools_to_call": []', '"tools_to_call": ["query_cities"]')
    manager2.add_assistant_message(ready_response)
    assert manager2.is_ready_to_query() == True
    assert "query_cities" in manager2.get_tools_to_call()
    print(f"✓ ready_to_query + tools_to_call propagate correctly")

    # 17. Turn and query limits
    assert not manager.at_turn_limit()    # turn=1, limit=12
    assert not manager.at_query_limit()   # query_count=0, limit=5
    print(f"✓ Limits: at_turn_limit=False, at_query_limit=False")

    # 18. Summary dict
    s = manager.summary()
    assert s["turn"] == 1
    assert s["message_count"] == 2
    assert s["has_weights"] == True
    assert s["at_turn_limit"] == False
    print(f"✓ summary(): {s}")

    print("─" * 50)
    print("Stages 1 + 2 complete.")
    print()

    # ── Stage 3: DB integration ────────────────────────────────
    print("Stage 3: DB integration")
    print("─" * 50)

    import uuid
    from db import create_conversation, get_messages

    # 19. persist_message strips state tags before saving
    test_cid = create_conversation()
    persist_message(test_cid, "user", "I want somewhere cheap.", turn_number=1)
    persist_message(test_cid, "assistant", mock_response, turn_number=1)  # has <state>
    saved = get_messages(test_cid)
    assert len(saved) == 2
    assert saved[0]["role"] == "user"
    assert "<state>" not in saved[1]["content"]   # stripped before save
    assert "That's really helpful" in saved[1]["content"]
    print(f"✓ persist_message: state stripped before DB write")

    # 20. load_from_db reconstructs manager from stored messages
    loaded = load_from_db(test_cid)
    assert loaded.conversation_id == test_cid
    assert len(loaded.raw_messages) == 2
    assert len(loaded.clean_messages) == 2
    assert loaded.turn == 1
    # Loaded messages are clean (no state tags) — expected tradeoff
    assert "<state>" not in loaded.raw_messages[1]["content"]
    print(f"✓ load_from_db: manager reconstructed, turn={loaded.turn}")

    # 21. Loaded manager can accept new messages normally
    loaded.add_user_message("I'm thinking Pacific Northwest.")
    assert loaded.turn == 2
    assert len(loaded.raw_messages) == 3
    print(f"✓ Loaded manager accepts new messages: turn={loaded.turn}")

    print("─" * 50)
    print("All stages complete. All checks passed.")