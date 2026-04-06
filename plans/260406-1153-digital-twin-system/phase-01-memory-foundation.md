---
phase: 1
title: Memory Foundation
status: Pending
priority: P1
effort: 8h
---

# Phase 1: Memory Foundation

## Context Links

- [Mem0 docs](https://docs.mem0.ai/open-source/quickstart)
- [pgvector extension](https://github.com/pgvector/pgvector)
- Existing Docker setup: `scripts/setup-bridge.sh` (Synapse + 2 Postgres instances at `~/.mautrix-googlechat/`)
- Existing state: `.claude/openkhang.local.md`, `.claude/gchat-inbox.jsonl`

## Overview

Stand up the three-layer memory system: episodic (event log), semantic (Mem0 + pgvector), working (active session context). This is the foundation every other phase depends on.

## Key Insights

- Mem0 graph memory: 26% accuracy gain over plain vector search via entity-relationship graph
- Three scoping levels: `user_id` (Khanh), `agent_id` (outward/inward), `session_id` (conversation)
- bge-m3 handles Vietnamese+English mixed content — critical for MoMo context
- Existing `gchat-inbox.jsonl` is the first data source to ingest

## Requirements

### Functional
- F1: Mem0 running as Docker service, accessible on internal network
- F2: PostgreSQL with pgvector extension, shared with existing bridge DB or separate
- F3: Memory CRUD API: add, search (semantic), get_related (graph), delete
- F4: Embedding via bge-m3 API endpoint (HuggingFace Inference API or self-hosted TEI)
- F5: Ingest existing `gchat-inbox.jsonl` into episodic + semantic layers

### Non-Functional
- NF1: Search latency <500ms for top-10 results
- NF2: Data persisted across container restarts (Docker volumes)
- NF3: Memory scoped per agent_id (outward vs inward modes)

## Architecture

```
┌──────────────────────────────────────────────┐
│           Memory Service (Python)             │
│                                               │
│  ┌─────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ Episodic │  │ Semantic  │  │   Working   │ │
│  │ (append  │  │ (Mem0 +   │  │  (in-memory │ │
│  │  event   │  │  pgvector  │  │   session)  │ │
│  │  log)    │  │  + graph) │  │             │ │
│  └────┬─────┘  └─────┬─────┘  └──────┬──────┘ │
│       │              │               │         │
│       └──────────────┼───────────────┘         │
│                      ▼                         │
│              PostgreSQL + pgvector              │
└──────────────────────────────────────────────┘
                       │
              bge-m3 Embedding API
```

### Data Flow

1. **Input**: Raw events (chat messages, Jira updates, commits) arrive via event bus
2. **Episodic**: Append-only table `events(id, source, type, payload, metadata, created_at)` — raw event log
3. **Semantic**: Mem0 processes events → extracts facts → embeds → stores in pgvector with graph relationships
4. **Working**: In-memory dict of current conversation context, flushed to episodic on session end
5. **Query**: Semantic search returns ranked memories; graph traversal returns related entities

## Related Code Files

### Create
- `services/memory/__init__.py` — package init
- `services/memory/config.py` — Mem0 + DB configuration
- `services/memory/client.py` — Memory client (add, search, get_related, delete)
- `services/memory/episodic.py` — Append-only event log (Postgres table)
- `services/memory/working.py` — In-memory session context
- `services/memory/schema.sql` — DB schema (events table, pgvector extension)
- `services/memory/ingest_history.py` — One-shot script: gchat-inbox.jsonl → memory
- `docker/mem0/Dockerfile` — Mem0 service container (if not using official image)
- `docker/postgres/init.sql` — pgvector extension + schema init

### Modify
- `scripts/setup-bridge.sh` — Add pgvector extension to existing Postgres OR create new instance
- `.env` — Add `MEM0_*`, `EMBEDDING_API_*` vars

### No Deletes

## Implementation Steps

1. **Add Postgres+pgvector to Docker Compose**
   - Create `docker-compose.yml` at project root (new file — bridge has its own at `~/.mautrix-googlechat/`)
   - Service: `postgres` with `pgvector/pgvector:pg16` image
   - Volume: `openkhang-pgdata`
   - Init script: enable `vector` extension, create `events` table and Mem0 tables

2. **Add Redis to Docker Compose**
   - Service: `redis` — used as event bus between services
   - Lightweight, no persistence needed (pub/sub only)

3. **Configure Mem0 Client**
   - Install `mem0ai` package
   - Configure to use the project Postgres with pgvector as vector store
   - Set embedding model to bge-m3 via API
   - Configure graph memory (Neo4j-lite mode using Postgres JSON if possible, else add Neo4j container)

4. **Create Memory Client (`services/memory/client.py`)**
   ```python
   class MemoryClient:
       def add(self, content: str, metadata: dict, agent_id: str) -> str
       def search(self, query: str, agent_id: str, limit: int = 10) -> list[dict]
       def get_related(self, entity: str) -> list[dict]
       def delete(self, memory_id: str) -> bool
       def get_all(self, agent_id: str, limit: int = 50) -> list[dict]
   ```

5. **Create Episodic Store (`services/memory/episodic.py`)**
   - Table: `events(id serial, source varchar, event_type varchar, payload jsonb, metadata jsonb, created_at timestamptz)`
   - Append-only: insert only, no updates/deletes
   - Query by source, type, time range

6. **Create Working Memory (`services/memory/working.py`)**
   - In-memory dict keyed by session_id
   - Methods: `set_context()`, `get_context()`, `flush_to_episodic()`
   - TTL: auto-flush after 30min inactivity

7. **Create History Ingestion Script**
   - Read `gchat-inbox.jsonl` line by line
   - For each message: add to episodic store + Mem0 semantic memory
   - Batch processing with progress indicator
   - Idempotent: skip if event_id already exists

8. **Add Environment Variables**
   - `DATABASE_URL=postgresql://openkhang:xxx@localhost:5433/openkhang`
   - `REDIS_URL=redis://localhost:6379`
   - `EMBEDDING_API_URL=` (HuggingFace Inference API endpoint for bge-m3)
   - `EMBEDDING_API_KEY=` (HF token)
   - `MEM0_CONFIG_PATH=services/memory/mem0_config.yaml`

9. **Write Integration Test**
   - Spin up Postgres+pgvector via docker compose
   - Add 10 test memories, search, verify recall
   - Test graph relationships
   - Test episodic append + query

## TODO

- [ ] Create `docker-compose.yml` with postgres+pgvector, redis
- [ ] Create `services/memory/schema.sql`
- [ ] Create `services/memory/config.py` with Mem0 configuration
- [ ] Create `services/memory/client.py` (MemoryClient class)
- [ ] Create `services/memory/episodic.py` (append-only event log)
- [ ] Create `services/memory/working.py` (session context)
- [ ] Create `services/memory/ingest_history.py` (gchat-inbox.jsonl loader)
- [ ] Add env vars to `.env.example`
- [ ] Decide: Mem0 graph via Neo4j container vs Postgres-only approach
- [ ] Write integration tests
- [ ] Verify bge-m3 API access and latency

## Success Criteria

1. `docker compose up postgres redis` starts without errors
2. `MemoryClient.add()` stores a memory and `search()` retrieves it with >0.7 similarity
3. Episodic store has all events from gchat-inbox.jsonl with correct timestamps
4. Graph query for a person name returns related chat rooms and topics
5. All operations complete in <500ms on local Docker

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Mem0 graph requires Neo4j (extra container) | Medium | Low | Start without graph, add Neo4j if needed; Mem0 works without graph mode |
| bge-m3 API rate limits | Low | Medium | Cache embeddings, batch requests, fallback to local sentence-transformers if needed |
| pgvector dimension mismatch | Low | High | Lock dimension to 1024 (bge-m3 output) in schema |
| Existing bridge Postgres conflict | Low | Low | Use separate Postgres instance on different port (5433) |

## Security Considerations

- Database credentials in `.env` (gitignored)
- Embedding API key in `.env` (gitignored)
- Memory contains real chat messages — never expose API without auth
- pgvector data at rest unencrypted (acceptable for local-only Docker)
- Redis pub/sub has no auth (local network only, acceptable)
