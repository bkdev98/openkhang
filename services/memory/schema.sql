-- openkhang memory layer schema
-- Run once on first Postgres start via docker-entrypoint-initdb.d

-- Extensions (required by Mem0 + episodic store)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Episodic: append-only raw event log
-- Sources: 'chat' | 'jira' | 'gitlab' | 'confluence'
CREATE TABLE IF NOT EXISTS events (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source       VARCHAR(50)  NOT NULL,
    event_type   VARCHAR(100) NOT NULL,
    actor        VARCHAR(255),
    payload      JSONB        NOT NULL,
    metadata     JSONB        NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_source     ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_type       ON events(event_type);

-- Draft replies queue
-- status: 'pending' | 'approved' | 'rejected' | 'edited'
CREATE TABLE IF NOT EXISTS draft_replies (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id        UUID         REFERENCES events(id),
    room_id         VARCHAR(255) NOT NULL,
    room_name       VARCHAR(255),
    original_message TEXT        NOT NULL,
    draft_text      TEXT         NOT NULL,
    confidence      FLOAT        NOT NULL,
    evidence        JSONB        NOT NULL DEFAULT '[]',
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ,
    reviewer_action VARCHAR(20)
);

CREATE INDEX IF NOT EXISTS idx_drafts_status ON draft_replies(status);
CREATE INDEX IF NOT EXISTS idx_drafts_room   ON draft_replies(room_id);

-- Ingestion sync state — tracks last successful sync per source
-- Sources: 'chat' | 'jira' | 'gitlab' | 'confluence'
CREATE TABLE IF NOT EXISTS sync_state (
    source          VARCHAR(50)  PRIMARY KEY,
    last_synced_at  TIMESTAMPTZ  DEFAULT NOW(),
    item_count      INTEGER      DEFAULT 0
);

-- Note: Mem0 creates its own tables (mem0_memories, etc.) automatically
-- when Memory() is first initialised. pgvector extension above is sufficient.

-- Workflow engine tables (Phase 4)

CREATE TABLE IF NOT EXISTS workflow_instances (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_name  VARCHAR(100) NOT NULL,
    current_state  VARCHAR(100) NOT NULL,
    context        JSONB        NOT NULL DEFAULT '{}',
    trigger_event  JSONB        NOT NULL DEFAULT '{}',
    status         VARCHAR(20)  NOT NULL DEFAULT 'active',
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_status ON workflow_instances(status);
CREATE INDEX IF NOT EXISTS idx_wf_name   ON workflow_instances(workflow_name);

CREATE TABLE IF NOT EXISTS audit_log (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id  UUID         REFERENCES workflow_instances(id),
    action_type  VARCHAR(100) NOT NULL,
    tier         INTEGER      NOT NULL DEFAULT 1,
    params       JSONB        NOT NULL DEFAULT '{}',
    result       JSONB        NOT NULL DEFAULT '{}',
    approved_by  VARCHAR(255),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_workflow ON audit_log(workflow_id);
CREATE INDEX IF NOT EXISTS idx_audit_created  ON audit_log(created_at);

-- Request traces — full pipeline observability per request
CREATE TABLE IF NOT EXISTS request_traces (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mode         VARCHAR(20),              -- 'outward' | 'inward'
    channel      VARCHAR(50),              -- 'matrix' | 'dashboard' | 'telegram'
    intent       VARCHAR(50),              -- classified intent
    skill_name   VARCHAR(100),             -- skill that handled the request
    action       VARCHAR(50),              -- 'auto_sent' | 'drafted' | 'inward_response' | 'skipped' | 'error'
    input_body   TEXT,                     -- original message (truncated)
    room_id      VARCHAR(255),
    sender_id    VARCHAR(255),
    confidence   FLOAT,
    tokens_used  INTEGER DEFAULT 0,
    latency_ms   INTEGER DEFAULT 0,
    error        TEXT DEFAULT '',
    steps        JSONB NOT NULL DEFAULT '[]',  -- ordered list of trace steps
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_traces_created ON request_traces(created_at);
CREATE INDEX IF NOT EXISTS idx_traces_mode    ON request_traces(mode);
CREATE INDEX IF NOT EXISTS idx_traces_action  ON request_traces(action);
