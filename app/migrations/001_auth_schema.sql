-- migrations/001_auth_schema.sql
-- Auth tables for Touchgrass Project 03
-- Run once against urbandb

-- Users table
CREATE TABLE IF NOT EXISTS app3.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(50)  UNIQUE NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    is_admin        BOOLEAN      NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMP
);

-- Server-side session tokens
CREATE TABLE IF NOT EXISTS app3.user_sessions (
    session_token   VARCHAR(64)  PRIMARY KEY,
    user_id         UUID         NOT NULL REFERENCES app3.users(id) ON DELETE CASCADE,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP    NOT NULL DEFAULT NOW() + INTERVAL '7 days',
    ip_address      VARCHAR(45),
    user_agent      TEXT,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE
);

-- Link existing conversations to users (nullable — existing rows stay intact)
ALTER TABLE app3.conversations
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES app3.users(id) ON DELETE SET NULL;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id    ON app3.user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_active     ON app3.user_sessions(is_active, expires_at);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id    ON app3.conversations(user_id);
