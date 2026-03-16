# app.py
# Project 03 — Touchgrass Conversational Agent
# FastAPI application. Four routes:
#
#   GET  /                              → serves index.html
#   POST /api/start                     → creates conversation, returns id
#   POST /api/chat                      → main conversation loop
#   GET  /api/results/{conversation_id} → latest scored cities
#
# CHAT LOOP (per turn):
#   1. Load or create ConversationManager
#   2. Add user message
#   3. Call Anthropic API
#   4. Add assistant response to manager
#   5. Check tools_to_call — execute if present
#   6. If tools ran, send results back to LLM for a follow-up response
#   7. Persist messages to DB
#   8. Check limits — fire log_conversation_close if done
#   9. Return clean response + any tool results to client

import os
import json
from pathlib import Path
from typing import Optional

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

from conversation import ConversationManager, load_from_db, persist_message
from tools import dispatch
from logger import log_conversation_close
from system_prompt import SYSTEM_PROMPT
from db import (
    create_conversation, create_conversation_for_user,
    conversation_exists, save_results, get_latest_results,
    get_user_conversations,
)
from auth import SESSION_COOKIE, validate_session
from routers.auth_routes import router as auth_router
from routers.admin_routes import router as admin_router
from routers.report_routes import router as report_router

load_dotenv()

app = FastAPI(title="Touchgrass Project 03")
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(report_router)

templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates")
)

# ─────────────────────────────────────────────
# AUTH MIDDLEWARE
# Protects all routes except /auth/* and /static/*.
# HTML requests → redirect to /auth/login
# API requests  → 401 JSON
# ─────────────────────────────────────────────

_PUBLIC_PATHS = {"/auth/login", "/auth/register", "/api/webhooks/stripe"}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Always allow auth routes and static assets
    if path in _PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)

    # Validate session cookie
    token = request.cookies.get(SESSION_COOKIE)
    user  = validate_session(token) if token else None

    if user is None:
        if path.startswith("/api/") or path.startswith("/admin/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        redirect_to = f"/auth/login?next={path}"
        return RedirectResponse(url=redirect_to, status_code=302)

    # Attach user to request state for downstream routes
    request.state.user = user
    return await call_next(request)

# In-memory manager store — keyed by conversation_id.
# Avoids a DB round-trip to reconstruct history on every turn.
# On server restart, managers are rebuilt from DB via load_from_db().
_managers: dict[str, ConversationManager] = {}

ANTHROPIC_MODEL = "claude-sonnet-4-20250514"

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")
    return anthropic.Anthropic(api_key=api_key)


def get_manager(conversation_id: str) -> ConversationManager:
    """
    Returns the in-memory manager for a conversation.
    If not in memory (e.g. after server restart), reconstructs
    from DB message history.
    """
    if conversation_id not in _managers:
        if not conversation_exists(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        _managers[conversation_id] = load_from_db(conversation_id)
    return _managers[conversation_id]


def call_llm(manager: ConversationManager) -> str:
    """
    Calls the Anthropic API with the full raw message history.
    Returns the raw response text including <state> tags.
    """
    client = get_client()
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=manager.get_api_messages(),
    )
    for block in response.content:
        if hasattr(block, "text"):
            return block.text  # type: ignore[union-attr]
    raise RuntimeError("No text block in Anthropic response")


def execute_tools(manager: ConversationManager) -> dict:
    """
    Executes any tools listed in tools_to_call from the latest state.
    Returns a dict of tool_name → result for all tools that ran.
    Only query_cities and get_city_detail are wired at MVP.
    Maps and charts are no-ops until tomorrow.
    """
    tools_to_call = manager.get_tools_to_call()
    if not tools_to_call:
        return {}

    results = {}
    weights  = manager.get_derived_weights()
    filters  = manager.get_filters()

    for tool_name in tools_to_call:
        if tool_name == "query_cities":
            result = dispatch("query_cities", weights=weights, filters=filters, limit=5)
            results["query_cities"] = result

            # If successful, format results and save to DB
            if result["success"] and weights is not None:
                fmt = dispatch("format_results", cities=result["cities"])
                results["format_results"] = fmt

                # Persist to DB for frontend retrieval
                save_results(
                    conversation_id=manager.conversation_id,
                    derived_weights=weights,
                    top_cities=result["cities"],
                    filters_applied=filters,
                    query_number=manager.query_count + 1,
                )

        elif tool_name == "get_city_detail":
            cbsa_code = manager.get_target_city_id()
            if cbsa_code:
                result = dispatch("get_city_detail", cbsa_code=cbsa_code)
                results["get_city_detail"] = result
            else:
                results["get_city_detail"] = {
                    "success": False,
                    "error":   "No target_city_id found in state.",
                }

        elif tool_name in ("generate_map", "generate_chart", "generate_stat_summary"):
            # Planned for v2 — no-op at MVP
            results[tool_name] = {"success": True, "status": "not_yet_implemented"}

        else:
            results[tool_name] = dispatch(tool_name)

    return results


def build_tool_context(tool_results: dict) -> Optional[str]:
    """
    Converts tool results into a context string to feed back to the LLM
    so it can present results in its next response.
    Returns None if no relevant results exist.
    """
    if not tool_results:
        return None

    parts = []

    if "format_results" in tool_results and tool_results["format_results"]["success"]:
        parts.append(
            "QUERY RESULTS — include these in your response to the user:\n\n"
            + tool_results["format_results"]["markdown"]
        )

    if "get_city_detail" in tool_results:
        detail_result = tool_results["get_city_detail"]
        if detail_result["success"]:
            d = detail_result["detail"]
            name = d.get("name", "this city")
            summary_lines = [f"CITY DETAIL FOR {name.upper()} — use these stats naturally in your response. Do not expose raw field names or score values. Cite numbers conversationally (e.g. 'median rent runs about $X/mo'):\n"]
            summary_lines.append(f"Population: {d.get('population'):,}" if d.get('population') else "")
            summary_lines.append(f"Median household income: ${int(d['median_household_income']):,}" if d.get('median_household_income') else "")
            summary_lines.append(f"Median gross rent: ${int(d['median_gross_rent']):,}/mo" if d.get('median_gross_rent') else "")
            summary_lines.append(f"Median home value: ${int(d['median_home_value']):,}" if d.get('median_home_value') else "")
            summary_lines.append(f"Poverty rate: {d.get('poverty_rate')}%" if d.get('poverty_rate') else "")
            summary_lines.append(f"Unemployment rate: {d.get('unemployment_rate')}%" if d.get('unemployment_rate') else "")
            summary_lines.append(f"Restaurant density (per sq mi): {round(float(d['poi_restaurant_density']), 1)}" if d.get('poi_restaurant_density') else "")
            summary_lines.append(f"Trail density (per sq mi): {round(float(d['poi_trail_density']), 1)}" if d.get('poi_trail_density') else "")
            summary_lines.append(f"Bachelor's degree or higher: {d.get('pct_bachelors_or_higher')}%" if d.get('pct_bachelors_or_higher') else "")
            summary_lines.append(f"Diversity index: {d.get('diversity_index')}" if d.get('diversity_index') else "")
            summary_lines.append(f"Avg commute time: {d.get('avg_commute_time_min')} min" if d.get('avg_commute_time_min') else "")
            summary_lines.append(f"Public transit usage: {d.get('pct_public_transit')}%" if d.get('pct_public_transit') else "")
            summary_lines.append(f"Air quality index (avg): {d.get('avg_aqi')} (lower is better)" if d.get('avg_aqi') else "")
            summary_lines.append(f"Health insurance coverage: {d.get('health_insurance_coverage')}%" if d.get('health_insurance_coverage') else "")
            summary_lines.append(f"Obesity rate: {d.get('obesity_rate')}%" if d.get('obesity_rate') else "")
            parts.append("\n".join(l for l in summary_lines if l))
        else:
            parts.append(
                f"TOOL ERROR: get_city_detail failed — "
                f"{detail_result.get('error', 'unknown error')}. "
                f"Acknowledge this to the user and offer to continue."
            )

    if "query_cities" in tool_results and not tool_results["query_cities"]["success"]:
        parts.append(
            f"TOOL ERROR: query_cities failed — "
            f"{tool_results['query_cities'].get('error', 'unknown error')}. "
            f"Acknowledge this to the user and offer to try again."
        )

    return "\n\n".join(parts) if parts else None


# ─────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────

class StartRequest(BaseModel):
    pass  # No body needed — conversation_id generated server-side


class ChatRequest(BaseModel):
    conversation_id: str
    message: str


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serves the chat UI."""
    index_path = Path(__file__).parent / "templates" / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return HTMLResponse(content=index_path.read_text())


@app.post("/api/start")
async def start_conversation(request: Request):
    """
    Creates a new conversation linked to the logged-in user.
    Returns the conversation_id and opening LLM message.
    """
    user_id = getattr(request.state, "user", {}).get("id")
    conversation_id = create_conversation_for_user(user_id)
    manager = ConversationManager(conversation_id)
    _managers[conversation_id] = manager

    # Get opening message from LLM — no user message yet,
    # so we seed with a minimal prompt to trigger the greeting.
    manager.add_user_message("hello")
    try:
        raw_response = call_llm(manager)
    except Exception as e:
        del _managers[conversation_id]
        raise HTTPException(status_code=500, detail=f"LLM call failed: {str(e)}")

    manager.add_assistant_message(raw_response)

    # Persist both seed message and opening response
    persist_message(conversation_id, "user", "hello", turn_number=1)
    persist_message(conversation_id, "assistant", raw_response, turn_number=1)

    return JSONResponse({
        "conversation_id": conversation_id,
        "message":         manager.get_latest_clean_response(),
    })


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Main conversation loop. Accepts a user message and returns
    the assistant response plus any tool results.

    Response shape:
    {
      "message":      str,         # clean assistant text
      "cities":       list | null, # ranked cities if query ran
      "query_ran":    bool,        # whether a city query executed
      "turn":         int,
      "at_limit":     bool,        # conversation ending soon
      "conversation_id": str
    }
    """
    manager = get_manager(request.conversation_id)

    if manager.at_turn_limit():
        return JSONResponse({
            "message":    "We've covered a lot of ground — I think we have "
                          "a solid picture of what you're looking for. "
                          "Check out your results above.",
            "cities":     None,
            "query_ran":  False,
            "turn":       manager.turn,
            "at_limit":   True,
            "conversation_id": request.conversation_id,
        })

    # 1. Add user message
    manager.add_user_message(request.message)
    persist_message(
        request.conversation_id, "user",
        request.message, turn_number=manager.turn
    )

    # 2. First LLM call
    try:
        raw_response = call_llm(manager)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM call failed: {str(e)}")

    manager.add_assistant_message(raw_response)

    # 3. Execute tools if LLM requested them
    tool_results = execute_tools(manager)
    cities = None
    query_ran = False

    if tool_results:
        query_ran = "query_cities" in tool_results and tool_results["query_cities"]["success"]
        if query_ran:
            cities = tool_results["query_cities"]["cities"]

        # 4. Feed tool results back to LLM for a follow-up response
        tool_context = build_tool_context(tool_results)
        if tool_context:
            manager.add_user_message(f"[TOOL RESULTS]\n{tool_context}")
            try:
                followup_response = call_llm(manager)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Follow-up LLM call failed: {str(e)}")

            manager.add_assistant_message(followup_response)

            # Persist tool context and follow-up (tool context not shown to user)
            persist_message(
                request.conversation_id, "user",
                f"[TOOL RESULTS]\n{tool_context}", turn_number=manager.turn
            )
            persist_message(
                request.conversation_id, "assistant",
                followup_response, turn_number=manager.turn
            )

    # 5. Persist first assistant response
    persist_message(
        request.conversation_id, "assistant",
        raw_response, turn_number=manager.turn
    )

    # 6. Close conversation if at limit
    at_limit = manager.at_turn_limit() or manager.at_query_limit()
    if at_limit:
        log_conversation_close(manager)

    return JSONResponse({
        "message":         manager.get_latest_clean_response(),
        "cities":          cities,
        "query_ran":       query_ran,
        "turn":            manager.turn,
        "at_limit":        at_limit,
        "conversation_id": request.conversation_id,
    })


@app.get("/api/me")
async def get_me(request: Request):
    """Returns the current user's basic info. Used by the frontend to show username."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return JSONResponse({
        "username": user["username"],
        "id":       user["id"],
        "is_admin": user["is_admin"],
    })


@app.get("/api/history")
async def get_history(request: Request):
    """Returns the logged-in user's conversation history for the history panel."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    conversations = get_user_conversations(user["id"])
    return JSONResponse({"conversations": conversations})


@app.get("/api/results/{conversation_id}")
async def get_results(conversation_id: str):
    """
    Returns the latest query results for a conversation.
    Used by the frontend to re-render results after a page reload.
    """
    if not conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    results = get_latest_results(conversation_id)
    if results is None:
        return JSONResponse({"cities": None, "query_ran": False})

    return JSONResponse({
        "cities":    results["top_cities"],
        "query_ran": True,
        "weights":   results["derived_weights"],
    })


@app.get("/api/city/{cbsa_code}")
async def get_city(cbsa_code: str):
    """
    Returns formatted stats for a single city.
    Called by the frontend when the user clicks 'View Stats'
    on a city card.

    Response shape:
    {
      "name":     str,
      "state":    str,
      "stats":    [ { "category", "label", "value", "descriptor" }, ... ]
    }
    """
    from score_engine import get_city_detail

    detail = get_city_detail(cbsa_code)
    if not detail:
        raise HTTPException(status_code=404, detail=f"City not found: {cbsa_code}")

    def fmt_currency(v):
        if v is None: return "N/A"
        return f"${int(round(v)):,}"

    def fmt_rent(v):
        if v is None: return "N/A"
        return f"${int(round(v)):,}/mo"

    def fmt_pct_decimal(v):
        # Value stored as decimal 0-1 (e.g. 0.62 → 62.0%)
        if v is None: return "N/A"
        return f"{round(float(v) * 100, 1)}%"

    def fmt_pct_whole(v):
        # Value stored as whole percentage (e.g. 49.55 → 49.6%)
        if v is None: return "N/A"
        return f"{round(float(v), 1)}%"

    def fmt_num(v, decimals=1):
        if v is None: return "N/A"
        return f"{round(float(v), decimals)}"

    def fmt_min(v):
        if v is None: return "N/A"
        return f"{round(float(v), 1)} min"

    def fmt_aqi(v):
        if v is None: return "N/A"
        return f"{round(float(v), 1)}"

    stats = [
        # Economic
        {
            "category":   "Economic",
            "label":      "Median Household Income",
            "value":      fmt_currency(detail.get("median_household_income")),
            "descriptor": "Higher income relative to costs drives the economic health score.",
        },
        {
            "category":   "Economic",
            "label":      "Median Gross Rent",
            "value":      fmt_rent(detail.get("median_gross_rent")),
            "descriptor": "Lower rent-to-income ratios improve the affordability sub-score.",
        },
        {
            "category":   "Economic",
            "label":      "Median Home Value",
            "value":      fmt_currency(detail.get("median_home_value")),
            "descriptor": "Home values relative to income drive the housing accessibility score.",
        },
        # Lifestyle
        {
            "category":   "Lifestyle",
            "label":      "Restaurant Density",
            "value":      fmt_num(detail.get("poi_restaurant_density")),
            "descriptor": "Restaurants per sq mile. Higher density drives the food & drink score.",
        },
        {
            "category":   "Lifestyle",
            "label":      "Trail Density",
            "value":      fmt_num(detail.get("poi_trail_density")),
            "descriptor": "Trails per sq mile. Key input to the outdoor access score.",
        },
        {
            "category":   "Lifestyle",
            "label":      "Cafe Density",
            "value":      fmt_num(detail.get("poi_cafe_density")),
            "descriptor": "Cafes per sq mile. Contributes to the food & social scene score.",
        },
        # Community
        {
            "category":   "Community",
            "label":      "Bachelor's Degree or Higher",
            "value":      fmt_pct_whole(detail.get("pct_bachelors_or_higher")),
            "descriptor": "Educational attainment drives the human capital sub-score.",
        },
        {
            "category":   "Community",
            "label":      "Diversity Index",
            "value":      fmt_num(detail.get("diversity_index")),
            "descriptor": "0-1 scale. Higher values indicate greater racial and ethnic diversity.",
        },
        {
            "category":   "Community",
            "label":      "Voter Turnout Rate",
            "value":      fmt_pct_whole(detail.get("voter_turnout_rate")),
            "descriptor": "Proxy for civic engagement -- drives the community civic sub-score.",
        },
        # Mobility
        {
            "category":   "Mobility",
            "label":      "Avg Commute Time",
            "value":      fmt_min(detail.get("avg_commute_time_min")),
            "descriptor": "Shorter commutes drive the commute sub-score.",
        },
        {
            "category":   "Mobility",
            "label":      "Public Transit Usage",
            "value":      fmt_pct_whole(detail.get("pct_public_transit")),
            "descriptor": "Share of commuters using transit. Drives the transit sub-score.",
        },
        {
            "category":   "Mobility",
            "label":      "Walk or Bike to Work",
            "value":      fmt_pct_whole(detail.get("pct_walk_or_bike")),
            "descriptor": "Active commuters as share of workforce. Contributes to transit score.",
        },
        # Health
        {
            "category":   "Health",
            "label":      "Air Quality Index (AQI)",
            "value":      fmt_aqi(detail.get("avg_aqi")),
            "descriptor": "Lower is better. AQI is the primary driver of the air quality score.",
        },
        {
            "category":   "Health",
            "label":      "Health Insurance Coverage",
            "value":      fmt_pct_whole(detail.get("health_insurance_coverage")),
            "descriptor": "Share of residents with coverage. Drives the healthcare access score.",
        },
        {
            "category":   "Health",
            "label":      "Obesity Rate",
            "value":      fmt_pct_whole(detail.get("obesity_rate")),
            "descriptor": "Lower rates contribute to better wellness outcome scores.",
        },
    ]

    return JSONResponse({
        "name":  detail.get("name"),
        "state": detail.get("state"),
        "stats": stats,
    })


# ─────────────────────────────────────────────
# DEV SERVER
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8003, reload=True)