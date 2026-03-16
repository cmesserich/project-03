-- Migration 002: paid_reports table
-- Tracks Stripe payment sessions and generated PDF reports.

CREATE TABLE IF NOT EXISTS app3.paid_reports (
    id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id      UUID         NOT NULL REFERENCES app3.conversations(id) ON DELETE CASCADE,
    user_id              UUID         REFERENCES app3.users(id) ON DELETE SET NULL,
    stripe_session_id    VARCHAR(255),
    stripe_payment_intent VARCHAR(255),
    amount_cents         INTEGER      NOT NULL DEFAULT 900,
    -- Status flow: pending → generating → ready | failed
    -- 'pending'    = checkout session created, payment not confirmed
    -- 'generating' = payment confirmed, PDF being built
    -- 'ready'      = PDF saved to disk, download available
    -- 'failed'     = PDF generation failed after payment
    status               VARCHAR(20)  NOT NULL DEFAULT 'pending',
    paid_at              TIMESTAMP,
    pdf_path             VARCHAR(500),
    pdf_generated_at     TIMESTAMP,
    created_at           TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paid_reports_conversation
    ON app3.paid_reports(conversation_id);

CREATE INDEX IF NOT EXISTS idx_paid_reports_user
    ON app3.paid_reports(user_id);

CREATE INDEX IF NOT EXISTS idx_paid_reports_stripe_session
    ON app3.paid_reports(stripe_session_id)
    WHERE stripe_session_id IS NOT NULL;
