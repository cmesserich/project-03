# tools.py
# Project 03 — Touchgrass Conversational Agent
#
# Tool execution layer. Called by app.py when ConversationManager
# reports tools_to_call in the latest LLM state.
#
# Tools available at MVP:
#   query_cities(weights, filters, limit)  → ranked city list
#   get_city_detail(cbsa_code)             → raw stats for one city
#   format_results(cities)                 → markdown string for LLM
#
# Tools planned for v2:
#   generate_map(cities)                   → map embed
#   generate_chart(cities, dimension)      → bar/radar chart
#
# DESIGN NOTES
# ─────────────
# - All tools are pure functions (no side effects, no DB writes)
# - DB logging happens in app.py after tool execution, not here
# - format_results is deterministic — consistent output regardless
#   of LLM mood, and presentation can be updated without touching
#   the system prompt
# - All tools return dicts with a "success" key so app.py can
#   handle errors uniformly without try/except at every call site

from typing import Optional
from score_engine import score_cities, get_city_detail, validate_weights


# ─────────────────────────────────────────────
# TOOL: query_cities
# ─────────────────────────────────────────────

def tool_query_cities(
    weights: dict,
    filters: Optional[dict] = None,
    limit: int = 5
) -> dict:
    """
    Scores and ranks cities based on a 16-key weight vector.
    Validates and normalizes weights before scoring.

    Args:
        weights: 16-key dict from LLM state derived_weights.
                 Will be validated and normalized before use.
        filters: Optional geographic filter dict.
                 {"states": [...], "exclude_states": [...]}
        limit:   Number of cities to return. Default 5.

    Returns:
        {
          "success": True,
          "cities": [...],        # ranked list from score_engine
          "weight_sum": 1.0,      # post-normalization sum
          "filters_applied": ..., # echo back what was used
          "city_count": 5
        }
        or on error:
        {
          "success": False,
          "error": "..."
        }
    """
    try:
        validated_weights = validate_weights(weights)
        cities = score_cities(validated_weights, filters=filters or {}, limit=limit)
        return {
            "success":         True,
            "cities":          cities,
            "weight_sum":      round(sum(validated_weights.values()), 4),
            "filters_applied": filters,
            "city_count":      len(cities),
        }
    except Exception as e:
        return {
            "success": False,
            "error":   f"query_cities failed: {str(e)}",
        }


# ─────────────────────────────────────────────
# TOOL: get_city_detail
# ─────────────────────────────────────────────

def tool_get_city_detail(cbsa_code: str) -> dict:
    """
    Fetches detailed raw stats for a single city across all
    five source tables (economic, lifestyle, health, mobility,
    community).

    Used when the user asks a follow-up question about a specific
    city — "tell me more about Portland" or "how's the job market
    in Minneapolis?"

    Args:
        cbsa_code: CBSA code string e.g. "42660" for Seattle

    Returns:
        {
          "success": True,
          "detail": { ... }   # full stat dict from score_engine
        }
        or on error:
        {
          "success": False,
          "error": "..."
        }
    """
    try:
        detail = get_city_detail(cbsa_code)
        if not detail:  # handles both None and empty dict {}
            return {
                "success": False,
                "error":   f"No city found for cbsa_code={cbsa_code}",
            }
        return {
            "success": True,
            "detail":  detail,
        }
    except Exception as e:
        return {
            "success": False,
            "error":   f"get_city_detail failed: {str(e)}",
        }


# ─────────────────────────────────────────────
# TOOL: format_results
# ─────────────────────────────────────────────

def tool_format_results(cities: list) -> dict:
    """
    Formats a ranked city list into clean markdown for the LLM
    to include in its response to the user.

    Deterministic — same input always produces same output.
    Presentation can be updated here without touching the system
    prompt or asking the LLM to format things differently.

    Args:
        cities: Ranked list from tool_query_cities()["cities"]

    Returns:
        {
          "success": True,
          "markdown": "..."   # formatted string ready for LLM use
        }
    """
    if not cities:
        return {
            "success":  True,
            "markdown": "_No cities matched your criteria._",
        }

    try:
        lines = []
        for city in cities:
            rank   = city.get("rank", "?")
            name   = city.get("name", "Unknown")
            state  = city.get("state", "")
            score  = city.get("personalized_score", 0)
            geo_id = city.get("geo_id", "")

            # Score bar — 10 chars wide, filled proportionally
            filled = round(score / 10)
            bar = "█" * filled + "░" * (10 - filled)

            lines.append(f"**{rank}. {name}**  `{bar}` {score:.1f}/100  [id:{geo_id}]")

            # Sub-scores if present — compact single line
            sub = city.get("sub_scores")
            if sub:
                parts = []
                labels = {
                    "econ":      "Econ",
                    "lifestyle": "Lifestyle",
                    "community": "Community",
                    "mobility":  "Mobility",
                    "health":    "Health",
                }
                for key, label in labels.items():
                    if key in sub:
                        parts.append(f"{label} {sub[key]:.0f}")
                if parts:
                    lines.append("   " + " · ".join(parts))

            lines.append("")  # blank line between cities

        return {
            "success":  True,
            "markdown": "\n".join(lines).strip(),
        }
    except Exception as e:
        return {
            "success": False,
            "error":   f"format_results failed: {str(e)}",
        }


# ─────────────────────────────────────────────
# DISPATCH
# ─────────────────────────────────────────────

TOOL_REGISTRY = {
    "query_cities":    tool_query_cities,
    "get_city_detail": tool_get_city_detail,
    "format_results":  tool_format_results,
}


def dispatch(tool_name: str, **kwargs) -> dict:
    """
    Calls a tool by name with kwargs.
    Returns the tool's result dict, or an error dict if the
    tool name is not registered.

    Usage in app.py:
        for tool_name in manager.get_tools_to_call():
            result = dispatch(tool_name, weights=w, filters=f)
    """
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return {
            "success": False,
            "error":   f"Unknown tool: '{tool_name}'. "
                       f"Available: {list(TOOL_REGISTRY.keys())}",
        }
    return fn(**kwargs)


# ─────────────────────────────────────────────
# SMOKE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("Running tools.py smoke test...")
    print("─" * 50)

    mock_weights = {
        "econ_wealth": 0.03, "econ_affordability": 0.20, "econ_housing": 0.15,
        "econ_inequality": 0.05, "lifestyle_food": 0.05, "lifestyle_arts": 0.04,
        "lifestyle_outdoor": 0.14, "community_capital": 0.04, "community_civic": 0.04,
        "community_equity": 0.04, "mobility_commute": 0.06, "mobility_transit": 0.06,
        "mobility_housing": 0.04, "health_air": 0.04, "health_access": 0.04,
        "health_outcomes": 0.04,
    }

    # 1. query_cities — happy path
    result = tool_query_cities(mock_weights, limit=3)
    assert result["success"] == True
    assert len(result["cities"]) == 3
    assert result["weight_sum"] == 1.0
    assert result["cities"][0]["personalized_score"] == 100.0
    print(f"✓ query_cities: top city = {result['cities'][0]['name']}, "
          f"count={result['city_count']}")

    # 2. query_cities — with state filter
    result_filtered = tool_query_cities(
        mock_weights,
        filters={"states": ["WA", "OR"], "exclude_states": []},
        limit=3
    )
    assert result_filtered["success"] == True
    assert result_filtered["filters_applied"] is not None
    states_returned = [c["state"] for c in result_filtered["cities"]]
    print(f"✓ query_cities with filter: states={states_returned}")

    # 3. query_cities — malformed weights still work (validate_weights normalizes)
    bad_weights = {"econ_affordability": 5.0}  # only one key, not normalized
    result_bad = tool_query_cities(bad_weights, limit=3)
    assert result_bad["success"] == True   # validate_weights fills missing keys
    print(f"✓ query_cities with partial weights: normalized and scored")

    # 4. get_city_detail — Seattle CBSA
    detail_result = tool_get_city_detail("42660")
    assert detail_result["success"] == True
    assert "name" in detail_result["detail"]
    assert "Seattle" in detail_result["detail"]["name"]
    print(f"✓ get_city_detail: {detail_result['detail']['name']}")

    # 5. get_city_detail — bad cbsa_code
    bad_detail = tool_get_city_detail("00000")
    assert bad_detail["success"] == False
    print(f"✓ get_city_detail bad code: error='{bad_detail['error']}'")

    # 6. format_results — full output
    cities = result["cities"]
    fmt = tool_format_results(cities)
    assert fmt["success"] == True
    assert "**1." in fmt["markdown"]
    assert "█" in fmt["markdown"]
    print(f"✓ format_results output:\n")
    print(fmt["markdown"])
    print()

    # 7. format_results — empty list
    empty_fmt = tool_format_results([])
    assert empty_fmt["success"] == True
    assert "No cities" in empty_fmt["markdown"]
    print(f"✓ format_results empty list: '{empty_fmt['markdown']}'")

    # 8. dispatch — known tool
    dispatched = dispatch("query_cities", weights=mock_weights, limit=2)
    assert dispatched["success"] == True
    assert len(dispatched["cities"]) == 2
    print(f"✓ dispatch query_cities: top={dispatched['cities'][0]['name']}")

    # 9. dispatch — unknown tool
    unknown = dispatch("generate_map", cities=[])
    assert unknown["success"] == False
    assert "Unknown tool" in unknown["error"]
    print(f"✓ dispatch unknown tool: error returned cleanly")

    print("─" * 50)
    print("All checks passed.")