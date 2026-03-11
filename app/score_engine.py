# score_engine.py
# Project 03 — Touchgrass Conversational Agent
#
# Scores and ranks cities using 16 sub-subindex weights derived
# directly from the LLM conversation. Clean implementation built
# for conversation-derived weights — not backward compatible with
# the 5-weight survey model in Project 02 by design.
#
# DB SCHEMA NOTES (verified 2026-03-10)
# --------------------------------------
# composite_index     — all 16 sub-subindex columns confirmed present
# metros              — join key: cbsa_code. state column is FULL NAME
#                       (e.g. "Washington"), not abbreviation
# economic_health     — joins on geo_id
# lifestyle_amenities — joins on geo_id
# health_wellness     — joins on geo_id
# mobility_access     — joins on geo_id
# community_civic     — joins on geo_id
# metro_stats         — does NOT exist. use source tables above.

import os
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# All 16 sub-subindex columns confirmed in composite_index table
SUB_SUBINDICES = [
    # Economic Health
    "econ_wealth",
    "econ_affordability",
    "econ_housing",
    "econ_inequality",
    # Lifestyle & Amenities
    "lifestyle_food",
    "lifestyle_arts",
    "lifestyle_outdoor",
    # Community & Civic
    "community_capital",
    "community_civic",
    "community_equity",
    # Mobility & Access
    "mobility_commute",
    "mobility_transit",
    "mobility_housing",
    # Health & Wellness
    "health_air",
    "health_access",
    "health_outcomes",
]

# Parent subindex grouping — used for display and rolled-up scores
PARENT_MAP = {
    "econ_wealth":        "econ",
    "econ_affordability": "econ",
    "econ_housing":       "econ",
    "econ_inequality":    "econ",
    "lifestyle_food":     "lifestyle",
    "lifestyle_arts":     "lifestyle",
    "lifestyle_outdoor":  "lifestyle",
    "community_capital":  "community",
    "community_civic":    "community",
    "community_equity":   "community",
    "mobility_commute":   "mobility",
    "mobility_transit":   "mobility",
    "mobility_housing":   "mobility",
    "health_air":         "health",
    "health_access":      "health",
    "health_outcomes":    "health",
}

# Default equal weights — used as fallback only
DEFAULT_WEIGHTS = {k: round(1.0 / len(SUB_SUBINDICES), 6) for k in SUB_SUBINDICES}

# Human-readable labels for UI display
DISPLAY_LABELS = {
    "econ_wealth":        "Wealth & Income",
    "econ_affordability": "Affordability",
    "econ_housing":       "Housing Market",
    "econ_inequality":    "Inequality & Labor",
    "lifestyle_food":     "Food & Drink",
    "lifestyle_arts":     "Arts & Culture",
    "lifestyle_outdoor":  "Outdoor Access",
    "community_capital":  "Human Capital",
    "community_civic":    "Civic Engagement",
    "community_equity":   "Equity & Inclusion",
    "mobility_commute":   "Commute",
    "mobility_transit":   "Transit & Walkability",
    "mobility_housing":   "Housing Flexibility",
    "health_air":         "Air Quality",
    "health_access":      "Healthcare Access",
    "health_outcomes":    "Wellness Outcomes",
}

PARENT_LABELS = {
    "econ":      "Economic Health",
    "lifestyle": "Lifestyle & Amenities",
    "community": "Community & Civic",
    "mobility":  "Mobility & Access",
    "health":    "Health & Wellness",
}

# metros.state is a full state name — LLM and system prompt use abbreviations
# Convert at query time so everything external stays abbr-based
STATE_NAME_MAP = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

# Reverse map for converting full names back to abbreviations for display
STATE_ABBR_MAP = {v: k for k, v in STATE_NAME_MAP.items()}


def metro_matches_states(metro_state: str, filter_abbrs: set) -> bool:
    """
    Check if a metro's state string contains any of the filter abbreviations.
    Handles multi-state metros like 'DC-VA-MD-WV', 'NY-NJ', 'OR-WA' by
    splitting on '-' and checking for intersection with the filter set.

    Examples:
        metro_state='OR-WA', filter_abbrs={'WA'} -> True
        metro_state='MN-WI', filter_abbrs={'MN'} -> True
        metro_state='CA',    filter_abbrs={'WA'}  -> False
    """
    metro_abbrs = set(metro_state.split("-"))
    return bool(metro_abbrs & filter_abbrs)


def get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT', 5432)}/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)


def validate_weights(weights: dict) -> dict:
    """
    Validates and normalizes a 16-weight vector.
    - Fills missing keys with a small default
    - Renormalizes so weights sum to exactly 1.0
    - Returns cleaned weight dict
    """
    cleaned = {}
    for key in SUB_SUBINDICES:
        val = weights.get(key, 0.02)
        cleaned[key] = max(0.0, float(val))

    total = sum(cleaned.values())
    if total == 0:
        return DEFAULT_WEIGHTS.copy()

    normalized = {k: round(v / total, 6) for k, v in cleaned.items()}

    # Fix floating point rounding drift — add remainder to highest weight
    diff = round(1.0 - sum(normalized.values()), 6)
    if diff != 0:
        top_key = max(normalized, key=lambda k: normalized[k])
        normalized[top_key] = round(normalized[top_key] + diff, 6)

    return normalized


def fetch_city_data() -> pd.DataFrame:
    """
    Pulls all 16 sub-subindex scores plus rolled-up parent scores
    for all metros. metros.state is full name — converted to abbr
    after fetch for display and filtering consistency.
    """
    cols = ", ".join(f"ci.{c}" for c in SUB_SUBINDICES)
    query = text(f"""
        SELECT
            ci.geo_id,
            m.name,
            m.state,
            ci.econ_score,
            ci.lifestyle_score,
            ci.community_score,
            ci.mobility_score,
            ci.health_score,
            {cols}
        FROM composite_index ci
        JOIN metros m ON ci.geo_id = m.cbsa_code
        WHERE ci.geo_level = 'metro'
        ORDER BY m.name
    """)
    with get_engine().connect() as conn:
        df = pd.read_sql(query, conn)

    # state column is already abbreviation-based (e.g. 'WA', 'OR-WA', 'DC-VA-MD-WV')
    # Use as-is — filtering handled by metro_matches_states()
    df["state_abbr"] = df["state"]

    for col in SUB_SUBINDICES:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.5)

    return df


def score_cities(weights: dict, filters: dict = None, limit: int = 10) -> list:
    """
    Main scoring function for Project 03.

    Takes a 16-weight vector derived from the LLM conversation,
    applies optional geographic filters, scores all cities,
    and returns a ranked list.

    Args:
        weights: dict of 16 sub-subindex weights summing to 1.0
        filters: optional dict with keys:
            states: list of state abbreviations to include
            exclude_states: list of state abbreviations to exclude
        limit: number of cities to return, default 10

    Returns:
        list of city dicts with rank, scores, and display data
    """
    weights = validate_weights(weights)
    df = fetch_city_data()

    # Filters use abbreviations — split on '-' to handle multi-state metros
    if filters:
        if filters.get("states"):
            include = set(filters["states"])
            mask = df["state"].apply(lambda s: metro_matches_states(s, include))
            df = df[mask]
        if filters.get("exclude_states"):
            exclude = set(filters["exclude_states"])
            mask = df["state"].apply(lambda s: metro_matches_states(s, exclude))
            df = df[~mask]

    if df.empty:
        return []

    # Weighted sum of all 16 sub-subindices
    df["personalized_score"] = sum(  # type: ignore[assignment]
        df[col] * weights[col] for col in SUB_SUBINDICES
    )

    # Normalize to 0-100 within the filtered set
    min_score = df["personalized_score"].min()
    max_score = df["personalized_score"].max()
    if max_score > min_score:
        df["personalized_score"] = (
            (df["personalized_score"] - min_score) /
            (max_score - min_score) * 100
        ).round(1)
    else:
        df["personalized_score"] = 50.0

    df["personalized_score"] = df["personalized_score"].fillna(0)
    df = df.sort_values("personalized_score", ascending=False).reset_index(drop=True)

    results = []
    for idx, row in df.head(limit).iterrows():
        sub_scores = {
            col: round(float(row[col]) * 100, 1)
            for col in SUB_SUBINDICES
        }

        parent_scores = {}
        for parent in ["econ", "lifestyle", "community", "mobility", "health"]:
            children = [k for k, v in PARENT_MAP.items() if v == parent]
            parent_scores[parent] = round(
                sum(float(row[c]) for c in children) / len(children) * 100, 1
            )

        results.append({
            "rank":               int(idx) + 1,
            "name":               row["name"],
            "state":              row["state_abbr"],
            "geo_id":             row["geo_id"],
            "personalized_score": float(row["personalized_score"]),
            "parent_scores":      parent_scores,
            "sub_scores":         sub_scores,
        })

    return results


def get_city_detail(cbsa_code: str) -> dict:
    """
    Returns full available stats for a single city by joining
    all five source tables. Used by the get_city_stats tool
    when the user wants to go deeper on a specific city.

    Source tables confirmed (metro_stats does not exist):
      economic_health, lifestyle_amenities, health_wellness,
      mobility_access, community_civic — all join on geo_id
    """
    query = text("""
        SELECT
            m.name,
            m.state,
            m.population,
            ci.geo_id,
            ci.econ_score,
            ci.lifestyle_score,
            ci.community_score,
            ci.mobility_score,
            ci.health_score,
            -- Economic Health
            eh.median_household_income,
            eh.per_capita_income,
            eh.median_gross_rent,
            eh.median_home_value,
            eh.homeownership_rate,
            eh.poverty_rate,
            eh.unemployment_rate,
            eh.rent_to_income_ratio,
            eh.housing_affordability_ratio,
            eh.cost_of_living_index,
            eh.job_growth_rate,
            eh.labor_force_participation,
            -- Lifestyle & Amenities
            la.poi_restaurant_density,
            la.poi_bar_density,
            la.poi_cafe_density,
            la.poi_park_density,
            la.poi_trail_density,
            la.poi_museum_density,
            la.poi_music_venue_density,
            la.poi_coworking_density,
            -- Health & Wellness
            hw.avg_aqi,
            hw.health_insurance_coverage_rate,
            hw.obesity_rate,
            hw.physical_inactivity_rate,
            hw.mental_health_poor_days,
            hw.poi_hospital_density,
            hw.poi_gym_density,
            hw.food_desert_pct,
            -- Mobility & Access
            ma.avg_commute_time_min,
            ma.pct_public_transit,
            ma.pct_drive_alone,
            ma.pct_no_vehicle,
            ma.pct_walk_or_bike,
            ma.bike_lane_density,
            ma.pct_renter_occupied,
            -- Community & Civic
            cc.pct_bachelors_or_higher,
            cc.diversity_index,
            cc.voter_turnout_rate,
            cc.child_poverty_rate,
            cc.median_age
        FROM composite_index ci
        JOIN metros m ON ci.geo_id = m.cbsa_code
        LEFT JOIN economic_health eh
            ON ci.geo_id = eh.geo_id AND eh.geo_level = 'metro'
        LEFT JOIN lifestyle_amenities la
            ON ci.geo_id = la.geo_id AND la.geo_level = 'metro'
        LEFT JOIN health_wellness hw
            ON ci.geo_id = hw.geo_id AND hw.geo_level = 'metro'
        LEFT JOIN mobility_access ma
            ON ci.geo_id = ma.geo_id AND ma.geo_level = 'metro'
        LEFT JOIN community_civic cc
            ON ci.geo_id = cc.geo_id AND cc.geo_level = 'metro'
        WHERE ci.geo_id = :cbsa_code
        AND ci.geo_level = 'metro'
    """)
    with get_engine().connect() as conn:
        result = conn.execute(query, {"cbsa_code": cbsa_code}).fetchone()

    if not result:
        return {}

    row = dict(result._mapping)
    # state column already stores abbreviations (e.g. 'WA', 'OR-WA')
    state_display = row.get("state", "")

    return {
        # Identity
        "name":                        row.get("name"),
        "state":                       state_display,
        "geo_id":                      row.get("geo_id"),
        "population":                  row.get("population"),
        # Economic
        "median_household_income":     row.get("median_household_income"),
        "per_capita_income":           row.get("per_capita_income"),
        "median_gross_rent":           row.get("median_gross_rent"),
        "median_home_value":           row.get("median_home_value"),
        "homeownership_rate":          row.get("homeownership_rate"),
        "rent_to_income_ratio":        row.get("rent_to_income_ratio"),
        "housing_affordability_ratio": row.get("housing_affordability_ratio"),
        "cost_of_living_index":        row.get("cost_of_living_index"),
        "poverty_rate":                row.get("poverty_rate"),
        "unemployment_rate":           row.get("unemployment_rate"),
        "job_growth_rate":             row.get("job_growth_rate"),
        "labor_force_participation":   row.get("labor_force_participation"),
        # Lifestyle
        "poi_restaurant_density":      row.get("poi_restaurant_density"),
        "poi_bar_density":             row.get("poi_bar_density"),
        "poi_cafe_density":            row.get("poi_cafe_density"),
        "poi_park_density":            row.get("poi_park_density"),
        "poi_trail_density":           row.get("poi_trail_density"),
        "poi_museum_density":          row.get("poi_museum_density"),
        "poi_music_venue_density":     row.get("poi_music_venue_density"),
        "poi_coworking_density":       row.get("poi_coworking_density"),
        # Health
        "avg_aqi":                     row.get("avg_aqi"),
        "health_insurance_coverage":   row.get("health_insurance_coverage_rate"),
        "obesity_rate":                row.get("obesity_rate"),
        "physical_inactivity_rate":    row.get("physical_inactivity_rate"),
        "mental_health_poor_days":     row.get("mental_health_poor_days"),
        "poi_hospital_density":        row.get("poi_hospital_density"),
        "poi_gym_density":             row.get("poi_gym_density"),
        "food_desert_pct":             row.get("food_desert_pct"),
        # Mobility
        "avg_commute_time_min":        row.get("avg_commute_time_min"),
        "pct_public_transit":          row.get("pct_public_transit"),
        "pct_drive_alone":             row.get("pct_drive_alone"),
        "pct_no_vehicle":              row.get("pct_no_vehicle"),
        "pct_walk_or_bike":            row.get("pct_walk_or_bike"),
        "bike_lane_density":           row.get("bike_lane_density"),
        "pct_renter_occupied":         row.get("pct_renter_occupied"),
        # Community
        "pct_bachelors_or_higher":     row.get("pct_bachelors_or_higher"),
        "diversity_index":             row.get("diversity_index"),
        "voter_turnout_rate":          row.get("voter_turnout_rate"),
        "child_poverty_rate":          row.get("child_poverty_rate"),
        "median_age":                  row.get("median_age"),
        # Rolled-up parent scores
        "parent_scores": {
            "econ":      round(float(row.get("econ_score") or 0) * 100, 1),
            "lifestyle": round(float(row.get("lifestyle_score") or 0) * 100, 1),
            "community": round(float(row.get("community_score") or 0) * 100, 1),
            "mobility":  round(float(row.get("mobility_score") or 0) * 100, 1),
            "health":    round(float(row.get("health_score") or 0) * 100, 1),
        }
    }


if __name__ == "__main__":
    # Test 1 — affordability focused (should hurt Seattle, reward Minneapolis)
    affordability_weights = {
        "econ_wealth":        0.03,
        "econ_affordability": 0.20,
        "econ_housing":       0.15,
        "econ_inequality":    0.05,
        "lifestyle_food":     0.05,
        "lifestyle_arts":     0.04,
        "lifestyle_outdoor":  0.06,
        "community_capital":  0.04,
        "community_civic":    0.04,
        "community_equity":   0.04,
        "mobility_commute":   0.06,
        "mobility_transit":   0.08,
        "mobility_housing":   0.04,
        "health_air":         0.04,
        "health_access":      0.04,
        "health_outcomes":    0.04,
    }

    # Test 2 — outdoor + clean air + transit (nature lover, car-free)
    outdoor_weights = {
        "econ_wealth":        0.03,
        "econ_affordability": 0.05,
        "econ_housing":       0.03,
        "econ_inequality":    0.03,
        "lifestyle_food":     0.06,
        "lifestyle_arts":     0.06,
        "lifestyle_outdoor":  0.20,
        "community_capital":  0.04,
        "community_civic":    0.04,
        "community_equity":   0.04,
        "mobility_commute":   0.03,
        "mobility_transit":   0.18,
        "mobility_housing":   0.03,
        "health_air":         0.10,
        "health_access":      0.04,
        "health_outcomes":    0.04,
    }

    print("Affordability focused (should NOT be Seattle #1):")
    print("─" * 55)
    for city in score_cities(affordability_weights):
        print(f"  {city['rank']:2}. {city['name']:<35} {city['personalized_score']}")

    print("\nOutdoor + transit focused:")
    print("─" * 55)
    for city in score_cities(outdoor_weights):
        print(f"  {city['rank']:2}. {city['name']:<35} {city['personalized_score']}")

    print("\nGeographic filter — Southeast only, affordability focused:")
    print("─" * 55)
    southeast = ["NC", "SC", "GA", "FL", "TN", "AL", "MS", "AR", "LA", "KY"]
    for city in score_cities(affordability_weights, filters={"states": southeast}):
        print(f"  {city['rank']:2}. {city['name']:<35} {city['personalized_score']}")