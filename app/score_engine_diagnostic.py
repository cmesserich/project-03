# score_engine_diagnostic.py
# Project 03 — Touchgrass Conversational Agent
#
# Diagnostic that simulates 30 realistic LLM-derived weight vectors
# representing distinct user personas and validates that the scoring
# engine produces meaningful variety across them.
#
# Each persona is modeled after a realistic conversation outcome —
# the kind of weight vector the LLM would derive after 4-6 turns
# of genuine conversation. Weights were assigned by hand following
# the same derivation guide in system_prompt.py.
#
# WHAT THIS TESTS
# ---------------
# 1. Score engine runs without errors on all 30 personas
# 2. #1 city varies meaningfully across personas (not always Seattle)
# 3. Full top-10 lists show reasonable geographic diversity
# 4. Geographic filters work correctly
# 5. Weight validation and normalization handles edge cases
# 6. No single city dominates across all personas
#
# RUN: python score_engine_diagnostic.py
# Expected runtime: ~15-30 seconds (30 DB queries)

from score_engine import score_cities, validate_weights, SUB_SUBINDICES
from collections import Counter

# ─────────────────────────────────────────────────────────────
# 30 REALISTIC PERSONAS
# Each dict: description, weights, optional filters
# Weights follow system_prompt.py derivation guide
# ─────────────────────────────────────────────────────────────

PERSONAS = [

    # ── ECONOMIC / COST FOCUSED ──────────────────────────────

    {
        "id": 1,
        "name": "Broke renter fleeing NYC",
        "description": "Paying 55% of income on rent, wants out, "
                       "doesn't care about much else as long as it's cheap",
        "weights": {
            "econ_wealth":        0.03,
            "econ_affordability": 0.28,
            "econ_housing":       0.18,
            "econ_inequality":    0.04,
            "lifestyle_food":     0.05,
            "lifestyle_arts":     0.03,
            "lifestyle_outdoor":  0.04,
            "community_capital":  0.04,
            "community_civic":    0.03,
            "community_equity":   0.03,
            "mobility_commute":   0.05,
            "mobility_transit":   0.06,
            "mobility_housing":   0.04,
            "health_air":         0.03,
            "health_access":      0.04,
            "health_outcomes":    0.03,
        },
    },

    {
        "id": 2,
        "name": "Remote worker maximizing savings",
        "description": "Earns $120k remotely, wants low COL, "
                       "doesn't care about job market or commute",
        "weights": {
            "econ_wealth":        0.02,
            "econ_affordability": 0.22,
            "econ_housing":       0.16,
            "econ_inequality":    0.03,
            "lifestyle_food":     0.08,
            "lifestyle_arts":     0.06,
            "lifestyle_outdoor":  0.10,
            "community_capital":  0.05,
            "community_civic":    0.03,
            "community_equity":   0.04,
            "mobility_commute":   0.02,
            "mobility_transit":   0.05,
            "mobility_housing":   0.04,
            "health_air":         0.04,
            "health_access":      0.03,
            "health_outcomes":    0.03,
        },
    },

    {
        "id": 3,
        "name": "First-time homebuyer",
        "description": "Wants to buy within 3 years, "
                       "home values and ownership rate are primary concern",
        "weights": {
            "econ_wealth":        0.08,
            "econ_affordability": 0.12,
            "econ_housing":       0.22,
            "econ_inequality":    0.04,
            "lifestyle_food":     0.06,
            "lifestyle_arts":     0.04,
            "lifestyle_outdoor":  0.06,
            "community_capital":  0.05,
            "community_civic":    0.04,
            "community_equity":   0.04,
            "mobility_commute":   0.07,
            "mobility_transit":   0.04,
            "mobility_housing":   0.03,
            "health_air":         0.03,
            "health_access":      0.04,
            "health_outcomes":    0.04,
        },
    },

    {
        "id": 4,
        "name": "Career climber, salary maximizer",
        "description": "Prioritizes high income, job growth, "
                       "labor market strength — cost is secondary",
        "weights": {
            "econ_wealth":        0.28,
            "econ_affordability": 0.04,
            "econ_housing":       0.06,
            "econ_inequality":    0.03,
            "lifestyle_food":     0.08,
            "lifestyle_arts":     0.06,
            "lifestyle_outdoor":  0.05,
            "community_capital":  0.10,
            "community_civic":    0.04,
            "community_equity":   0.04,
            "mobility_commute":   0.06,
            "mobility_transit":   0.06,
            "mobility_housing":   0.03,
            "health_air":         0.03,
            "health_access":      0.04,
            "health_outcomes":    0.00,
        },
    },

    {
        "id": 5,
        "name": "Equity-focused progressive",
        "description": "Cares deeply about inequality, poverty, "
                       "diversity — economic justice over personal wealth",
        "weights": {
            "econ_wealth":        0.03,
            "econ_affordability": 0.08,
            "econ_housing":       0.05,
            "econ_inequality":    0.20,
            "lifestyle_food":     0.06,
            "lifestyle_arts":     0.07,
            "lifestyle_outdoor":  0.05,
            "community_capital":  0.06,
            "community_civic":    0.10,
            "community_equity":   0.15,
            "mobility_commute":   0.03,
            "mobility_transit":   0.04,
            "mobility_housing":   0.03,
            "health_air":         0.02,
            "health_access":      0.02,
            "health_outcomes":    0.01,
        },
    },

    # ── LIFESTYLE / CULTURE FOCUSED ──────────────────────────

    {
        "id": 6,
        "name": "Foodie and nightlife seeker",
        "description": "Restaurant density, bar scene, cafe culture "
                       "are top priority — art scene also matters",
        "weights": {
            "econ_wealth":        0.04,
            "econ_affordability": 0.06,
            "econ_housing":       0.03,
            "econ_inequality":    0.03,
            "lifestyle_food":     0.30,
            "lifestyle_arts":     0.15,
            "lifestyle_outdoor":  0.05,
            "community_capital":  0.05,
            "community_civic":    0.03,
            "community_equity":   0.05,
            "mobility_commute":   0.04,
            "mobility_transit":   0.07,
            "mobility_housing":   0.03,
            "health_air":         0.02,
            "health_access":      0.03,
            "health_outcomes":    0.02,
        },
    },

    {
        "id": 7,
        "name": "Arts and culture devotee",
        "description": "Museums, music venues, theater, bookstores — "
                       "wants a creative city, not just a food scene",
        "weights": {
            "econ_wealth":        0.04,
            "econ_affordability": 0.06,
            "econ_housing":       0.03,
            "econ_inequality":    0.04,
            "lifestyle_food":     0.10,
            "lifestyle_arts":     0.30,
            "lifestyle_outdoor":  0.05,
            "community_capital":  0.08,
            "community_civic":    0.05,
            "community_equity":   0.06,
            "mobility_commute":   0.03,
            "mobility_transit":   0.07,
            "mobility_housing":   0.03,
            "health_air":         0.02,
            "health_access":      0.02,
            "health_outcomes":    0.02,
        },
    },

    {
        "id": 8,
        "name": "Outdoor recreation obsessive",
        "description": "Hiking, trails, parks, nature — "
                       "will sacrifice cost and culture for green space",
        "weights": {
            "econ_wealth":        0.03,
            "econ_affordability": 0.05,
            "econ_housing":       0.03,
            "econ_inequality":    0.02,
            "lifestyle_food":     0.05,
            "lifestyle_arts":     0.03,
            "lifestyle_outdoor":  0.32,
            "community_capital":  0.04,
            "community_civic":    0.03,
            "community_equity":   0.03,
            "mobility_commute":   0.04,
            "mobility_transit":   0.08,
            "mobility_housing":   0.03,
            "health_air":         0.12,
            "health_access":      0.04,
            "health_outcomes":    0.06,
        },
    },

    {
        "id": 9,
        "name": "Balanced lifestyle seeker",
        "description": "Wants it all — good food, culture, outdoors, "
                       "reasonable cost. No single dominant priority.",
        "weights": {
            "econ_wealth":        0.04,
            "econ_affordability": 0.10,
            "econ_housing":       0.06,
            "econ_inequality":    0.04,
            "lifestyle_food":     0.12,
            "lifestyle_arts":     0.10,
            "lifestyle_outdoor":  0.12,
            "community_capital":  0.06,
            "community_civic":    0.04,
            "community_equity":   0.05,
            "mobility_commute":   0.06,
            "mobility_transit":   0.07,
            "mobility_housing":   0.04,
            "health_air":         0.04,
            "health_access":      0.04,
            "health_outcomes":    0.02,
        },
    },

    # ── MOBILITY / TRANSIT FOCUSED ───────────────────────────

    {
        "id": 10,
        "name": "Car-free urbanist",
        "description": "No car, wants walkability, bike lanes, "
                       "dense transit — commute by foot or transit only",
        "weights": {
            "econ_wealth":        0.03,
            "econ_affordability": 0.08,
            "econ_housing":       0.03,
            "econ_inequality":    0.03,
            "lifestyle_food":     0.08,
            "lifestyle_arts":     0.06,
            "lifestyle_outdoor":  0.06,
            "community_capital":  0.04,
            "community_civic":    0.04,
            "community_equity":   0.05,
            "mobility_commute":   0.02,
            "mobility_transit":   0.28,
            "mobility_housing":   0.06,
            "health_air":         0.05,
            "health_access":      0.04,
            "health_outcomes":    0.05,
        },
    },

    {
        "id": 11,
        "name": "Short commute above all else",
        "description": "Burned out on 90-minute commutes, "
                       "wants to live close to work, drive time is everything",
        "weights": {
            "econ_wealth":        0.06,
            "econ_affordability": 0.08,
            "econ_housing":       0.06,
            "econ_inequality":    0.03,
            "lifestyle_food":     0.07,
            "lifestyle_arts":     0.04,
            "lifestyle_outdoor":  0.06,
            "community_capital":  0.04,
            "community_civic":    0.03,
            "community_equity":   0.03,
            "mobility_commute":   0.28,
            "mobility_transit":   0.08,
            "mobility_housing":   0.04,
            "health_air":         0.04,
            "health_access":      0.04,
            "health_outcomes":    0.02,
        },
    },

    {
        "id": 12,
        "name": "Flexible renter, wants mobility",
        "description": "Doesn't want to be locked in, "
                       "high renter rate and housing flexibility matter",
        "weights": {
            "econ_wealth":        0.05,
            "econ_affordability": 0.14,
            "econ_housing":       0.03,
            "econ_inequality":    0.04,
            "lifestyle_food":     0.08,
            "lifestyle_arts":     0.06,
            "lifestyle_outdoor":  0.06,
            "community_capital":  0.05,
            "community_civic":    0.04,
            "community_equity":   0.05,
            "mobility_commute":   0.06,
            "mobility_transit":   0.10,
            "mobility_housing":   0.16,
            "health_air":         0.04,
            "health_access":      0.03,
            "health_outcomes":    0.01,
        },
    },

    # ── HEALTH / WELLNESS FOCUSED ────────────────────────────

    {
        "id": 13,
        "name": "Clean air / environment obsessed",
        "description": "Has asthma, allergies — AQI is non-negotiable, "
                       "green space and outdoor access also elevated",
        "weights": {
            "econ_wealth":        0.03,
            "econ_affordability": 0.07,
            "econ_housing":       0.04,
            "econ_inequality":    0.03,
            "lifestyle_food":     0.05,
            "lifestyle_arts":     0.04,
            "lifestyle_outdoor":  0.14,
            "community_capital":  0.04,
            "community_civic":    0.03,
            "community_equity":   0.03,
            "mobility_commute":   0.04,
            "mobility_transit":   0.06,
            "mobility_housing":   0.03,
            "health_air":         0.25,
            "health_access":      0.06,
            "health_outcomes":    0.06,
        },
    },

    {
        "id": 14,
        "name": "Healthcare dependent",
        "description": "Has chronic condition, needs reliable hospital "
                       "access, high insurance coverage rate essential",
        "weights": {
            "econ_wealth":        0.05,
            "econ_affordability": 0.08,
            "econ_housing":       0.04,
            "econ_inequality":    0.04,
            "lifestyle_food":     0.05,
            "lifestyle_arts":     0.03,
            "lifestyle_outdoor":  0.05,
            "community_capital":  0.05,
            "community_civic":    0.03,
            "community_equity":   0.04,
            "mobility_commute":   0.05,
            "mobility_transit":   0.06,
            "mobility_housing":   0.03,
            "health_air":         0.06,
            "health_access":      0.24,
            "health_outcomes":    0.10,
        },
    },

    {
        "id": 15,
        "name": "Fitness and wellness lifestyle",
        "description": "Gym culture, active population, low obesity, "
                       "mental health matters — wants a healthy city",
        "weights": {
            "econ_wealth":        0.04,
            "econ_affordability": 0.07,
            "econ_housing":       0.04,
            "econ_inequality":    0.03,
            "lifestyle_food":     0.06,
            "lifestyle_arts":     0.04,
            "lifestyle_outdoor":  0.14,
            "community_capital":  0.05,
            "community_civic":    0.03,
            "community_equity":   0.04,
            "mobility_commute":   0.05,
            "mobility_transit":   0.06,
            "mobility_housing":   0.03,
            "health_air":         0.08,
            "health_access":      0.08,
            "health_outcomes":    0.16,
        },
    },

    # ── COMMUNITY / CIVIC FOCUSED ────────────────────────────

    {
        "id": 16,
        "name": "Civically engaged activist",
        "description": "Voter turnout, civic engagement, "
                       "community involvement — wants an engaged city",
        "weights": {
            "econ_wealth":        0.04,
            "econ_affordability": 0.07,
            "econ_housing":       0.03,
            "econ_inequality":    0.10,
            "lifestyle_food":     0.05,
            "lifestyle_arts":     0.08,
            "lifestyle_outdoor":  0.05,
            "community_capital":  0.10,
            "community_civic":    0.22,
            "community_equity":   0.10,
            "mobility_commute":   0.03,
            "mobility_transit":   0.05,
            "mobility_housing":   0.03,
            "health_air":         0.02,
            "health_access":      0.02,
            "health_outcomes":    0.01,
        },
    },

    {
        "id": 17,
        "name": "Diversity and inclusion seeker",
        "description": "Wants a diverse, inclusive community — "
                       "diversity index and equity are top signals",
        "weights": {
            "econ_wealth":        0.04,
            "econ_affordability": 0.07,
            "econ_housing":       0.03,
            "econ_inequality":    0.12,
            "lifestyle_food":     0.08,
            "lifestyle_arts":     0.07,
            "lifestyle_outdoor":  0.05,
            "community_capital":  0.07,
            "community_civic":    0.08,
            "community_equity":   0.22,
            "mobility_commute":   0.03,
            "mobility_transit":   0.06,
            "mobility_housing":   0.03,
            "health_air":         0.02,
            "health_access":      0.02,
            "health_outcomes":    0.01,
        },
    },

    {
        "id": 18,
        "name": "Education-obsessed parent",
        "description": "Has two kids, wants high education attainment, "
                       "broadband, low child poverty — schools matter most",
        "weights": {
            "econ_wealth":        0.06,
            "econ_affordability": 0.08,
            "econ_housing":       0.08,
            "econ_inequality":    0.06,
            "lifestyle_food":     0.05,
            "lifestyle_arts":     0.05,
            "lifestyle_outdoor":  0.08,
            "community_capital":  0.20,
            "community_civic":    0.06,
            "community_equity":   0.10,
            "mobility_commute":   0.05,
            "mobility_transit":   0.04,
            "mobility_housing":   0.02,
            "health_air":         0.03,
            "health_access":      0.03,
            "health_outcomes":    0.01,
        },
    },

    # ── COMBINED / COMPLEX PERSONAS ──────────────────────────

    {
        "id": 19,
        "name": "Retiring boomer, low stress",
        "description": "Retiring soon, fixed income, wants low cost, "
                       "good healthcare access, clean air, no traffic",
        "weights": {
            "econ_wealth":        0.03,
            "econ_affordability": 0.16,
            "econ_housing":       0.10,
            "econ_inequality":    0.04,
            "lifestyle_food":     0.06,
            "lifestyle_arts":     0.05,
            "lifestyle_outdoor":  0.07,
            "community_capital":  0.04,
            "community_civic":    0.04,
            "community_equity":   0.03,
            "mobility_commute":   0.08,
            "mobility_transit":   0.04,
            "mobility_housing":   0.03,
            "health_air":         0.08,
            "health_access":      0.12,
            "health_outcomes":    0.03,
        },
    },

    {
        "id": 20,
        "name": "Young professional, big city feel",
        "description": "26, just got first real job, wants energy, "
                       "food scene, arts, transit — doesn't mind rent",
        "weights": {
            "econ_wealth":        0.10,
            "econ_affordability": 0.04,
            "econ_housing":       0.03,
            "econ_inequality":    0.03,
            "lifestyle_food":     0.18,
            "lifestyle_arts":     0.15,
            "lifestyle_outdoor":  0.06,
            "community_capital":  0.08,
            "community_civic":    0.04,
            "community_equity":   0.06,
            "mobility_commute":   0.04,
            "mobility_transit":   0.12,
            "mobility_housing":   0.03,
            "health_air":         0.02,
            "health_access":      0.01,
            "health_outcomes":    0.01,
        },
    },

    {
        "id": 21,
        "name": "Nature + affordability combo",
        "description": "Wants outdoor access AND low cost — "
                       "willing to sacrifice culture and nightlife",
        "weights": {
            "econ_wealth":        0.03,
            "econ_affordability": 0.18,
            "econ_housing":       0.12,
            "econ_inequality":    0.03,
            "lifestyle_food":     0.03,
            "lifestyle_arts":     0.02,
            "lifestyle_outdoor":  0.22,
            "community_capital":  0.04,
            "community_civic":    0.03,
            "community_equity":   0.03,
            "mobility_commute":   0.05,
            "mobility_transit":   0.04,
            "mobility_housing":   0.04,
            "health_air":         0.08,
            "health_access":      0.04,
            "health_outcomes":    0.02,
        },
    },

    {
        "id": 22,
        "name": "Transit + culture urbanist",
        "description": "Wants walkable, transit-rich neighborhood "
                       "with strong arts scene — classic urban liberal",
        "weights": {
            "econ_wealth":        0.04,
            "econ_affordability": 0.06,
            "econ_housing":       0.03,
            "econ_inequality":    0.06,
            "lifestyle_food":     0.10,
            "lifestyle_arts":     0.16,
            "lifestyle_outdoor":  0.06,
            "community_capital":  0.07,
            "community_civic":    0.06,
            "community_equity":   0.07,
            "mobility_commute":   0.03,
            "mobility_transit":   0.18,
            "mobility_housing":   0.04,
            "health_air":         0.04,
            "health_access":      0.03,
            "health_outcomes":    0.03,
        },
    },

    {
        "id": 23,
        "name": "Health + outdoor combo",
        "description": "Active lifestyle, wants clean air, trails, "
                       "gyms, low obesity — wellness is the whole identity",
        "weights": {
            "econ_wealth":        0.03,
            "econ_affordability": 0.06,
            "econ_housing":       0.03,
            "econ_inequality":    0.03,
            "lifestyle_food":     0.05,
            "lifestyle_arts":     0.03,
            "lifestyle_outdoor":  0.20,
            "community_capital":  0.04,
            "community_civic":    0.03,
            "community_equity":   0.03,
            "mobility_commute":   0.04,
            "mobility_transit":   0.06,
            "mobility_housing":   0.03,
            "health_air":         0.16,
            "health_access":      0.06,
            "health_outcomes":    0.12,
        },
    },

    {
        "id": 24,
        "name": "Midwest pragmatist",
        "description": "Practical, wants good job market, "
                       "affordable housing, short commute — Midwest open",
        "weights": {
            "econ_wealth":        0.12,
            "econ_affordability": 0.14,
            "econ_housing":       0.12,
            "econ_inequality":    0.05,
            "lifestyle_food":     0.07,
            "lifestyle_arts":     0.04,
            "lifestyle_outdoor":  0.06,
            "community_capital":  0.06,
            "community_civic":    0.04,
            "community_equity":   0.04,
            "mobility_commute":   0.12,
            "mobility_transit":   0.04,
            "mobility_housing":   0.04,
            "health_air":         0.03,
            "health_access":      0.03,
            "health_outcomes":    0.00,
        },
        "filters": {"states": ["OH", "IN", "IL", "MI", "WI", "MN", "IA", "MO"]},
    },

    {
        "id": 25,
        "name": "Southeast budget seeker",
        "description": "Wants cheap Southeast city with decent "
                       "job market and reasonable quality of life",
        "weights": {
            "econ_wealth":        0.08,
            "econ_affordability": 0.18,
            "econ_housing":       0.12,
            "econ_inequality":    0.05,
            "lifestyle_food":     0.07,
            "lifestyle_arts":     0.05,
            "lifestyle_outdoor":  0.07,
            "community_capital":  0.06,
            "community_civic":    0.04,
            "community_equity":   0.05,
            "mobility_commute":   0.07,
            "mobility_transit":   0.03,
            "mobility_housing":   0.04,
            "health_air":         0.03,
            "health_access":      0.04,
            "health_outcomes":    0.02,
        },
        "filters": {"states": ["NC", "SC", "GA", "FL", "TN", "AL", "VA"]},
    },

    {
        "id": 26,
        "name": "West Coast transplant, staying West",
        "description": "Leaving San Francisco, wants to stay West Coast "
                       "but needs relief on housing costs",
        "weights": {
            "econ_wealth":        0.06,
            "econ_affordability": 0.16,
            "econ_housing":       0.12,
            "econ_inequality":    0.04,
            "lifestyle_food":     0.10,
            "lifestyle_arts":     0.08,
            "lifestyle_outdoor":  0.12,
            "community_capital":  0.06,
            "community_civic":    0.04,
            "community_equity":   0.06,
            "mobility_commute":   0.03,
            "mobility_transit":   0.06,
            "mobility_housing":   0.03,
            "health_air":         0.02,
            "health_access":      0.01,
            "health_outcomes":    0.01,
        },
        "filters": {"states": ["WA", "OR", "CA", "CO", "NV", "AZ"]},
    },

    {
        "id": 27,
        "name": "Avoiding cold weather",
        "description": "Hates winter, wants South or Southwest, "
                       "outdoor access year-round, low cost preferred",
        "weights": {
            "econ_wealth":        0.05,
            "econ_affordability": 0.14,
            "econ_housing":       0.08,
            "econ_inequality":    0.04,
            "lifestyle_food":     0.08,
            "lifestyle_arts":     0.05,
            "lifestyle_outdoor":  0.16,
            "community_capital":  0.04,
            "community_civic":    0.03,
            "community_equity":   0.04,
            "mobility_commute":   0.06,
            "mobility_transit":   0.05,
            "mobility_housing":   0.04,
            "health_air":         0.08,
            "health_access":      0.05,
            "health_outcomes":    0.01,
        },
        "filters": {"states": ["FL", "TX", "AZ", "NV", "NM", "GA", "SC", "NC"]},
    },

    {
        "id": 28,
        "name": "Everything but California",
        "description": "Done with California costs and politics, "
                       "open to anywhere else",
        "weights": {
            "econ_wealth":        0.06,
            "econ_affordability": 0.20,
            "econ_housing":       0.14,
            "econ_inequality":    0.04,
            "lifestyle_food":     0.08,
            "lifestyle_arts":     0.06,
            "lifestyle_outdoor":  0.10,
            "community_capital":  0.05,
            "community_civic":    0.04,
            "community_equity":   0.04,
            "mobility_commute":   0.05,
            "mobility_transit":   0.05,
            "mobility_housing":   0.03,
            "health_air":         0.03,
            "health_access":      0.02,
            "health_outcomes":    0.01,
        },
        "filters": {"exclude_states": ["CA"]},
    },

    {
        "id": 29,
        "name": "Coworking remote worker, coffee shop regular",
        "description": "Works from cafes and coworking spaces, "
                       "wants dense cafe/coworking scene, walkable, affordable",
        "weights": {
            "econ_wealth":        0.03,
            "econ_affordability": 0.14,
            "econ_housing":       0.06,
            "econ_inequality":    0.03,
            "lifestyle_food":     0.16,
            "lifestyle_arts":     0.10,
            "lifestyle_outdoor":  0.06,
            "community_capital":  0.08,
            "community_civic":    0.04,
            "community_equity":   0.05,
            "mobility_commute":   0.02,
            "mobility_transit":   0.12,
            "mobility_housing":   0.05,
            "health_air":         0.03,
            "health_access":      0.02,
            "health_outcomes":    0.01,
        },
    },

    {
        "id": 30,
        "name": "Truly equal weights (baseline)",
        "description": "No strong priorities — "
                       "tests equal weight baseline behavior",
        "weights": {k: round(1.0 / 16, 6) for k in SUB_SUBINDICES},
    },
]


# ─────────────────────────────────────────────────────────────
# DIAGNOSTIC RUNNER
# ─────────────────────────────────────────────────────────────

def run_diagnostics():
    print("\n" + "═" * 70)
    print("  TOUCHGRASS PROJECT 03 — SCORING ENGINE DIAGNOSTIC")
    print("  30 Persona Weight Vectors | Variety & Coverage Test")
    print("═" * 70)

    results_by_persona = []
    number_one_counter = Counter()
    top_three_counter = Counter()
    errors = []

    for persona in PERSONAS:
        pid   = persona["id"]
        name  = persona["name"]
        desc  = persona["description"]
        w     = persona["weights"]
        filt  = persona.get("filters")

        # Validate weights sum
        validated = validate_weights(w)
        weight_sum = round(sum(validated.values()), 4)

        try:
            results = score_cities(validated, filters=filt, limit=10)
        except Exception as e:
            errors.append((pid, name, str(e)))
            continue

        if not results:
            errors.append((pid, name, "Empty results — filter too narrow?"))
            continue

        top = results[0]
        number_one_counter[top["name"]] += 1
        for r in results[:3]:
            top_three_counter[r["name"]] += 1

        results_by_persona.append({
            "persona":    persona,
            "results":    results,
            "weight_sum": weight_sum,
        })

        # Print persona summary
        filter_str = f"  [filter: {filt}]" if filt else ""
        print(f"\n{'─' * 70}")
        print(f"  #{pid:02d} {name}{filter_str}")
        print(f"  {desc}")
        print(f"  Weight sum: {weight_sum}")
        print(f"  {'Rank':<6} {'City':<35} {'Score':>6}")
        for r in results[:5]:
            print(f"  {r['rank']:<6} {r['name'] + ', ' + r['state']:<35} {r['personalized_score']:>6}")

    # ── SUMMARY STATS ─────────────────────────────────────────

    print("\n" + "═" * 70)
    print("  SUMMARY")
    print("═" * 70)

    total_ran    = len(results_by_persona)
    total_errors = len(errors)
    unique_no1   = len(number_one_counter)

    print(f"\n  Personas run:       {total_ran}/30")
    print(f"  Errors:             {total_errors}")
    print(f"  Unique #1 cities:   {unique_no1}")
    print(f"  {'Pass' if unique_no1 >= 6 else 'WARN — low variety'}: "
          f"target is 6+ unique cities reaching #1")

    print(f"\n  #1 City Distribution ({unique_no1} unique):")
    for city, count in number_one_counter.most_common():
        bar = "█" * count
        print(f"    {city:<35} {bar} ({count})")

    print(f"\n  Top 3 Appearances (breadth check):")
    for city, count in top_three_counter.most_common(15):
        bar = "█" * count
        print(f"    {city:<35} {bar} ({count})")

    if errors:
        print(f"\n  ERRORS:")
        for pid, name, msg in errors:
            print(f"    #{pid:02d} {name}: {msg}")

    # ── DOMINANCE CHECK ───────────────────────────────────────

    print(f"\n  Dominance check (any city #1 in >8 personas = concern):")
    for city, count in number_one_counter.most_common(3):
        flag = " ⚠ HIGH" if count > 8 else " ✓"
        print(f"    {city:<35} {count:>3} times{flag}")

    # ── WEIGHT SUM VALIDATION ─────────────────────────────────

    bad_sums = [p for p in results_by_persona if p["weight_sum"] != 1.0]
    print(f"\n  Weight sum validation: "
          f"{'All 1.0 ✓' if not bad_sums else f'{len(bad_sums)} invalid sums ⚠'}")

    print("\n" + "═" * 70 + "\n")


if __name__ == "__main__":
    run_diagnostics()
