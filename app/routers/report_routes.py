# routers/report_routes.py
# Touchgrass — Report purchase and download routes
#
# Routes:
#   GET  /api/report/status/{conversation_id}  → check payment + PDF status
#   POST /api/report/checkout/{conversation_id} → create Stripe Checkout session
#   POST /api/webhooks/stripe                   → Stripe payment webhook (public)
#   GET  /api/report/download/{report_id}       → serve the PDF file

import os
import json
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from db import (
    conversation_exists,
    create_paid_report,
    get_paid_report_by_conversation,
    get_paid_report,
    mark_report_paid,
    mark_report_ready,
    mark_report_failed,
)
from report import generate_report_pdf

router = APIRouter()

REPORT_PRICE_CENTS = int(os.getenv("REPORT_PRICE_CENTS", "900"))
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8003")


def _stripe():
    """Returns the stripe module with api_key set. Raises 500 if not configured."""
    import stripe as _stripe_lib
    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="Stripe is not configured.")
    _stripe_lib.api_key = key
    return _stripe_lib


def _generate_in_background(conversation_id: str, report_id: str) -> None:
    """Kicks off PDF generation in a daemon thread after payment confirmation."""
    def _run():
        try:
            path = generate_report_pdf(conversation_id, report_id)
            mark_report_ready(report_id, path)
        except Exception as exc:
            print(f"[report] PDF generation failed for {report_id}: {exc}")
            mark_report_failed(report_id)

    threading.Thread(target=_run, daemon=True).start()


# ─────────────────────────────────────────────
# STATUS
# ─────────────────────────────────────────────

@router.get("/api/report/status/{conversation_id}")
async def report_status(conversation_id: str, request: Request):
    """
    Returns the purchase and PDF generation status for a conversation.
    Used by the frontend to show the correct CTA state.

    Response:
        { status: "unpaid" }
        { status: "pending" | "generating" | "ready" | "failed", report_id: str, pdf_ready: bool }
    """
    if not conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    report = get_paid_report_by_conversation(conversation_id)
    if report is None:
        return JSONResponse({"status": "unpaid"})

    return JSONResponse({
        "status":    report["status"],
        "report_id": report["id"],
        "pdf_ready": report["status"] == "ready",
    })


# ─────────────────────────────────────────────
# CHECKOUT
# ─────────────────────────────────────────────

@router.post("/api/report/checkout/{conversation_id}")
async def create_checkout(conversation_id: str, request: Request):
    """
    Creates a Stripe Checkout session for the report purchase.
    Returns { checkout_url } to redirect the user to Stripe.
    If already paid, returns { already_paid: true, ... } instead.
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Idempotency: don't create a new session if already paid/generating/ready
    existing = get_paid_report_by_conversation(conversation_id)
    if existing and existing["status"] in ("generating", "ready"):
        return JSONResponse({
            "already_paid": True,
            "report_id":    existing["id"],
            "status":       existing["status"],
            "pdf_ready":    existing["status"] == "ready",
        })

    s = _stripe()
    session = s.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency":     "usd",
                "unit_amount":  REPORT_PRICE_CENTS,
                "product_data": {
                    "name":        "Touchgrass Relocation Report",
                    "description": (
                        "Your personalized relocation report — ranked cities, "
                        "metro maps, full stats breakdown, and comparison matrix."
                    ),
                },
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=(
            f"{APP_BASE_URL}/?report_success=1"
            f"&conversation_id={conversation_id}"
        ),
        cancel_url=f"{APP_BASE_URL}/?conversation_id={conversation_id}",
        metadata={
            "conversation_id": conversation_id,
            "user_id":         user["id"],
        },
    )

    create_paid_report(
        conversation_id=conversation_id,
        user_id=user["id"],
        stripe_session_id=session.id,
        amount_cents=REPORT_PRICE_CENTS,
    )

    return JSONResponse({"checkout_url": session.url})


# ─────────────────────────────────────────────
# STRIPE WEBHOOK
# ─────────────────────────────────────────────

@router.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request):
    """
    Stripe sends this event after a successful payment.
    We mark the report as paid and kick off async PDF generation.
    This endpoint is public (no session cookie required).
    """
    payload     = await request.body()
    sig_header  = request.headers.get("stripe-signature", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    import stripe as _stripe_lib
    _stripe_lib.api_key = os.getenv("STRIPE_SECRET_KEY", "")

    try:
        if webhook_secret:
            event = _stripe_lib.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        else:
            # Dev mode: no signature verification
            event = json.loads(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Webhook error: {exc}")

    if event["type"] == "checkout.session.completed":
        session        = event["data"]["object"]
        session_id     = session["id"]
        payment_intent = session.get("payment_intent", "")
        conversation_id = session.get("metadata", {}).get("conversation_id")

        report_id = mark_report_paid(session_id, payment_intent)
        if report_id and conversation_id:
            _generate_in_background(conversation_id, report_id)

    return JSONResponse({"received": True})


# ─────────────────────────────────────────────
# DOWNLOAD
# ─────────────────────────────────────────────

@router.get("/api/report/download/{report_id}")
async def download_report(report_id: str, request: Request):
    """
    Serves the generated PDF. The requesting user must own the report
    (or be an admin). Returns 202 if the PDF is not ready yet.
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    report = get_paid_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    if not user["is_admin"] and report["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    if report["status"] != "ready":
        return JSONResponse(
            {"status": report["status"], "message": "Report is not ready yet."},
            status_code=202,
        )

    pdf_path = Path(report["pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    short_id = report["conversation_id"][:8]
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"touchgrass-report-{short_id}.pdf",
    )
