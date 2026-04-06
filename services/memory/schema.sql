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

-- Note: Mem0 creates its own tables (mem0_memories, etc.) automatically
-- when Memory() is first initialised. pgvector extension above is sufficient.
