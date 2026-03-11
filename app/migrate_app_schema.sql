-- migrate_app_schema.sql
-- Project 03 — Touchgrass Conversational Agent
-- Run once on the server to create the app3 schema and tables.
--
-- Run with:
--   docker exec -i project01-postgis psql -U urban -d urbandb < migrate_app_schema.sql

-- ─────────────────────────────────────────────────────────────
-- SCHEMA
-- ─────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS app3;

-- ─────────────────────────────────────────────────────────────
-- CONVERSATIONS
-- One row per conversation session.
-- Created when a user lands on the chat page.
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS app3.conversations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at          TIMESTAMP DEFAULT NOW(),
    last_active_at      TIMESTAMP DEFAULT NOW(),
    completed           BOOLEAN DEFAULT FALSE,
    turn_count          INTEGER DEFAULT 0,
    query_count         INTEGER DEFAULT 0
);

-- ─────────────────────────────────────────────────────────────
-- MESSAGES
-- Full message history per conversation.
-- role: 'user' | 'assistant'
-- Assistant messages stored with <state> tags stripped.
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS app3.messages (
    id                  SERIAL PRIMARY KEY,
    conversation_id     UUID REFERENCES app3.conversations(id) ON DELETE CASCADE,
    role                VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content             TEXT NOT NULL,
    created_at          TIMESTAMP DEFAULT NOW(),
    turn_number         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON app3.messages(conversation_id);

-- ─────────────────────────────────────────────────────────────
-- CONVERSATION RESULTS
-- One row per query_cities call (max 5 per conversation).
-- Stores derived weights + ranked city results at time of query.
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS app3.conversation_results (
    id                  SERIAL PRIMARY KEY,
    conversation_id     UUID REFERENCES app3.conversations(id) ON DELETE CASCADE,
    created_at          TIMESTAMP DEFAULT NOW(),
    query_number        INTEGER DEFAULT 1,
    derived_weights     JSONB NOT NULL,
    filters_applied     JSONB,
    top_cities          JSONB NOT NULL,
    weight_sum          NUMERIC(6,4)
);

CREATE INDEX IF NOT EXISTS idx_results_conversation_id
    ON app3.conversation_results(conversation_id);

-- ─────────────────────────────────────────────────────────────
-- CONVERSATION SIGNALS
-- Written async at conversation close.
-- Core ML training dataset — conversation text → weight vector.
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS app3.conversation_signals (
    id                  SERIAL PRIMARY KEY,
    conversation_id     UUID REFERENCES app3.conversations(id) ON DELETE CASCADE,
    created_at          TIMESTAMP DEFAULT NOW(),
    final_weight_vector JSONB,
    named_cities        TEXT[],
    named_states        TEXT[],
    budget_mentioned    BOOLEAN DEFAULT FALSE,
    remote_work         BOOLEAN DEFAULT FALSE,
    has_kids            BOOLEAN DEFAULT FALSE,
    turn_count          INTEGER,
    raw_signal_notes    TEXT
);
