# report.py
# Touchgrass — PDF Report Generation
#
# Public API:
#   generate_report_pdf(conversation_id, report_id) → str   (path to saved PDF)
#   generate_report_bytes(conversation_id)           → bytes (for preview/admin)
#
# Flow:
#   1. Fetch conversation results, weights, and signals from DB
#   2. For each of the top 5 cities: fetch detail stats + render metro map PNG
#   3. Render pdf_report.html Jinja2 template with all data
#   4. Convert HTML → PDF via WeasyPrint
#   5. Save to /app/reports/{report_id}.pdf

import io
import json
import base64
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

# Non-interactive matplotlib backend — must be set before pyplot import
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from shapely.geometry import shape as shapely_shape  # noqa: E402
from jinja2 import Environment, FileSystemLoader  # noqa: E402
import weasyprint  # noqa: E402
from sqlalchemy import text  # noqa: E402

from db import get_engine  # noqa: E402
from score_engine import (  # noqa: E402
    get_city_detail, DISPLAY_LABELS, PARENT_LABELS, PARENT_MAP, DEFAULT_WEIGHTS,
)

REPORTS_DIR  = Path("/app/reports")
TEMPLATES_DIR = Path(__file__).parent / "templates"


def _ensure_reports_dir() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# MAP GENERATION
# ─────────────────────────────────────────────

def _get_metro_geojson(geo_id: str) -> Optional[str]:
    """Fetch metro polygon as GeoJSON string from PostGIS."""
    with get_engine().connect() as conn:
        row = conn.execute(text("""
            SELECT ST_AsGeoJSON(geometry) AS geojson
            FROM public.metros
            WHERE cbsa_code = :geo_id
        """), {"geo_id": geo_id}).fetchone()
    return row.geojson if (row and row.geojson) else None


def _generate_city_map(geo_id: str) -> Optional[str]:
    """
    Renders the metro boundary as a base64-encoded PNG.
    Returns None if geometry is unavailable or rendering fails.
    """
    geojson_str = _get_metro_geojson(geo_id)
    if not geojson_str:
        return None

    try:
        geom = shapely_shape(json.loads(geojson_str))
        fig, ax = plt.subplots(figsize=(5, 3.5))
        fig.patch.set_facecolor("#f9f7f4")
        ax.set_facecolor("#f9f7f4")

        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        for poly in polys:
            x, y = poly.exterior.xy
            ax.fill(x, y, fc="#C8B89A", ec="#8a7a5a", alpha=0.65, linewidth=1.2)
            for interior in poly.interiors:
                xi, yi = interior.xy
                ax.fill(xi, yi, fc="#f9f7f4", ec="#8a7a5a", linewidth=0.7)

        bounds = geom.bounds  # (minx, miny, maxx, maxy)
        dx = (bounds[2] - bounds[0]) * 0.15
        dy = (bounds[3] - bounds[1]) * 0.15
        ax.set_xlim(bounds[0] - dx, bounds[2] + dx)
        ax.set_ylim(bounds[1] - dy, bounds[3] + dy)
        ax.set_aspect("equal")
        ax.axis("off")

        buf = io.BytesIO()
        fig.savefig(
            buf, format="png", bbox_inches="tight",
            dpi=150, facecolor=fig.get_facecolor(), edgecolor="none",
        )
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except Exception as exc:
        plt.close("all")
        print(f"[report] map generation failed for {geo_id}: {exc}")
        return None


# ─────────────────────────────────────────────
# DATA ASSEMBLY
# ─────────────────────────────────────────────

def _get_report_data(conversation_id: str) -> Optional[dict]:
    """
    Assembles all data needed to render the PDF template.
    Returns None if the conversation has no results.
    """
    with get_engine().connect() as conn:
        meta = conn.execute(text("""
            SELECT c.id, c.created_at, u.username
            FROM app3.conversations c
            LEFT JOIN app3.users u ON u.id = c.user_id
            WHERE c.id = :id
        """), {"id": conversation_id}).fetchone()

        if meta is None:
            return None

        result_row = conn.execute(text("""
            SELECT derived_weights, top_cities
            FROM app3.conversation_results
            WHERE conversation_id = :id
            ORDER BY created_at DESC
            LIMIT 1
        """), {"id": conversation_id}).fetchone()

        if result_row is None:
            return None

        signals_row = conn.execute(text("""
            SELECT named_cities, named_states, budget_mentioned,
                   remote_work, has_kids, raw_signal_notes
            FROM app3.conversation_signals
            WHERE conversation_id = :id
            LIMIT 1
        """), {"id": conversation_id}).fetchone()

    raw_weights    = result_row.derived_weights or {}
    top_cities_raw = result_row.top_cities or []

    if not top_cities_raw:
        return None

    # Use personalized weights if present, otherwise fall back to equal weights
    weights_personalized = bool(raw_weights)
    weights = raw_weights if weights_personalized else DEFAULT_WEIGHTS

    # Enrich top 5 cities with detail stats and map images
    cities = []
    for city in top_cities_raw[:5]:
        geo_id  = str(city.get("geo_id", ""))
        detail  = get_city_detail(geo_id) if geo_id else {}
        map_png = _generate_city_map(geo_id) if geo_id else None
        cities.append({
            "rank":          city.get("rank", len(cities) + 1),
            "name":          city.get("name", "Unknown"),
            "state":         city.get("state", ""),
            "score":         round(float(city.get("personalized_score", 0)), 1),
            "geo_id":        geo_id,
            "parent_scores": city.get("parent_scores", {}),
            "detail":        detail or {},
            "map_png":       map_png,
        })

    # Group weights by parent category for the priorities page
    weight_groups: dict = {}
    max_weight = max(weights.values()) if weights else 1.0
    for key, val in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        parent = PARENT_MAP.get(key, "other")
        weight_groups.setdefault(parent, []).append({
            "key":       key,
            "label":     DISPLAY_LABELS.get(key, key),
            "value":     val,
            "pct":       round(val * 100, 1),
            "bar_width": min(int(val / max_weight * 100), 100),
        })

    signals = None
    if signals_row:
        signals = {
            "named_cities":     signals_row.named_cities or [],
            "named_states":     signals_row.named_states or [],
            "budget_mentioned": signals_row.budget_mentioned,
            "remote_work":      signals_row.remote_work,
            "has_kids":         signals_row.has_kids,
            "raw_signal_notes": signals_row.raw_signal_notes,
        }

    return {
        "conversation_id":    conversation_id,
        "username":           meta.username or "Anonymous",
        "generated_at":       datetime.now().strftime("%B %d, %Y"),
        "cities":             cities,
        "weights":            weights,
        "weight_groups":      weight_groups,
        "weights_personalized": weights_personalized,
        "parent_labels":      PARENT_LABELS,
        "display_labels":     DISPLAY_LABELS,
        "signals":            signals,
        "top_cities_summary": top_cities_raw[:10],
    }


# ─────────────────────────────────────────────
# PDF RENDERING
# ─────────────────────────────────────────────

def _render_html(data: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("pdf_report.html")
    return template.render(**data)


def generate_report_bytes(conversation_id: str) -> bytes:
    """
    Generates a PDF and returns the raw bytes.
    Used for admin preview without saving to disk.
    Raises ValueError if conversation has no results.
    """
    data = _get_report_data(conversation_id)
    if data is None:
        raise ValueError(f"No results found for conversation {conversation_id}")
    html = _render_html(data)
    return weasyprint.HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()


def generate_report_pdf(conversation_id: str, report_id: str) -> str:
    """
    Generates the PDF, saves it to disk, and returns the absolute path.
    Used after Stripe payment confirmation.
    Raises ValueError if conversation has no results.
    """
    _ensure_reports_dir()
    data = _get_report_data(conversation_id)
    if data is None:
        raise ValueError(f"No results found for conversation {conversation_id}")
    html = _render_html(data)
    pdf_bytes = weasyprint.HTML(
        string=html, base_url=str(TEMPLATES_DIR)
    ).write_pdf()
    pdf_path = REPORTS_DIR / f"{report_id}.pdf"
    pdf_path.write_bytes(pdf_bytes)
    return str(pdf_path)
