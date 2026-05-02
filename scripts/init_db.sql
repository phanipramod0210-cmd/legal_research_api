-- scripts/init_db.sql
-- Initial schema bootstrapped directly via SQL (Alembic handles migrations thereafter)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For future full-text search on scenario_text

-- ── API Keys ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key_hash         VARCHAR(128) NOT NULL UNIQUE,
    name             VARCHAR(100) NOT NULL,
    description      TEXT,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    requests_today   INTEGER NOT NULL DEFAULT 0,
    requests_total   INTEGER NOT NULL DEFAULT 0,
    daily_limit      INTEGER NOT NULL DEFAULT 100,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at     TIMESTAMPTZ,
    expires_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash     ON api_keys (key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_active   ON api_keys (is_active);

-- ── Analyses ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analyses (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scenario_text       TEXT,
    file_name           VARCHAR(255),
    file_size_bytes     BIGINT,
    extracted_text      TEXT,
    content_hash        VARCHAR(64),
    jurisdiction        VARCHAR(50)  NOT NULL,
    legal_area          VARCHAR(100) NOT NULL DEFAULT 'Auto-detect',
    client_side         VARCHAR(20)  NOT NULL DEFAULT 'defence',
    source_type         VARCHAR(20)  NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'pending',
    error_message       TEXT,
    result              JSONB,
    token_usage         JSONB,
    processing_time_ms  INTEGER,
    cache_hit           BOOLEAN NOT NULL DEFAULT FALSE,
    llm_calls           INTEGER NOT NULL DEFAULT 0,
    api_key_id          UUID REFERENCES api_keys(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analyses_status         ON analyses (status);
CREATE INDEX IF NOT EXISTS idx_analyses_content_hash   ON analyses (content_hash);
CREATE INDEX IF NOT EXISTS idx_analyses_created_at     ON analyses (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analyses_jurisdiction   ON analyses (jurisdiction);
CREATE INDEX IF NOT EXISTS idx_analyses_api_key        ON analyses (api_key_id);
-- GIN index on JSONB result for fast key-level queries
CREATE INDEX IF NOT EXISTS idx_analyses_result         ON analyses USING GIN (result);
