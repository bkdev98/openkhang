# openkhang: Digital Twin for Work Persona

**Version:** 0.1.0  
**Status:** Phase 6: Integration & Polish  
**Owner:** Khanh Bui (@quocs)

## Product Vision

openkhang is an AI digital twin that acts as an autonomous agent for Khanh Bui (Senior Mobile Engineer at MoMo fintech). The twin integrates four knowledge sources (Google Chat, Jira, Confluence, GitLab) and uses a three-layer memory system to reply to colleagues in Khanh's voice, manage tasks, monitor pipelines, and assist with work decisions — always respecting safety constraints and confidence thresholds.

## Dual-Mode Operation

### Outward Mode: "Act As Me"
- Monitors Google Chat messages in spaces where Khanh participates
- Classifies messages: work request, question, social, greeting, fyi
- Generates draft replies grounded in RAG (retrieved memory + code context)
- Auto-sends low-confidence replies; high-confidence replies require human review
- Respects hard constraints: never claims to attend meetings, never shares confidential data, never commits without verifying code state
- Languages: Vietnamese + English (Vinglish code-switching)

### Inward Mode: "Be My Assistant"
- Dashboard at localhost:8000 shows activity feed, draft queue, task summaries
- User reviews drafts, approves/rejects/edits before send
- Twin Chat feature: conversation with the agent for queries ("What did we discuss about transaction history?")
- Service health monitoring: postgres, redis, embedding API, matrix-listener, dashboard
- Inbox relay: consolidates mentions, assignments, and flagged items
- Agent relay: direct instructions to agent ("Reply to #eng-chat message 123 about the deployment issue")

## Memory Architecture

### Layer 1: Semantic (Vector Search)
- Storage: pgvector extension on Postgres 5433
- Embeddings: BAAI/bge-m3 via OpenRouter API (1024-dim, Vietnamese+English)
- Index: HNSW vector index managed by pgvector
- Use: "What does Khanh know about transaction history?"

### Layer 2: Episodic (Event Log)
- Storage: append-only `events` table in Postgres
- Sources: chat messages, Jira updates, GitLab MRs, Confluence docs, code changes
- Metadata: actor, timestamp, source, event_type, payload
- Use: "What happened in the last 7 days?" "Did we discuss this issue before?"

### Layer 3: Working (Session Context)
- Storage: in-memory TTL cache (30-min default)
- Contains: current conversation context, recent drafts, user preferences
- Use: Real-time conversation state without querying Postgres for every message

## Knowledge Sources & Ingestion

| Source | Ingestor | Schedule | Chunk Size | Purpose |
|--------|----------|----------|-----------|---------|
| Google Chat | `ChatIngestor` | Real-time (via matrix-listener) | Paragraph/message | Conversation history, context, voice examples |
| Jira | `JiraIngestor` | 30min polling | Ticket summary + comments | Sprint status, task context, blockers |
| GitLab | `GitLabIngestor` | 30min polling | MR description + commits | Code changes, PR comments, pipeline status |
| Confluence | `ConfluenceIngestor` | 1h polling | Page + sections | Docs, design decisions, architecture notes |
| Code | `CodeIngestor` | On-demand | Class/function (semantic chunks) | Implementation details, APIs, patterns |

All ingested data flows through:
1. **Chunker** — splits by semantic boundaries
2. **Embedder** — vectorizes via BAAI/bge-m3 (OpenRouter API)
3. **Mem0 Client** — stores in pgvector with metadata
4. **Episodic Store** — appends raw event to `events` table

## Confidence Scoring & Gating

Confidence score (0.0–1.0) determines auto-send decision:

```
confidence = base_score * room_modifier * sender_modifier * history_modifier
```

- **base_score:** LLM answer confidence (0.0–1.0)
- **room_modifier:** 0.9 if DM, 1.2 if group (lower threshold for DMs)
- **sender_modifier:** 0.8 if manager/lead, 1.0 otherwise
- **history_modifier:** +0.1 if Khanh has replied to similar messages before

**Auto-Send Rules (per `confidence_thresholds.yaml`):**
- **DM (1:1 chat):** Send if confidence ≥ 0.75
- **Group chat:** Send if confidence ≥ 0.85 (conservative)
- **From leads/managers:** Always draft, regardless of confidence
- **Group work requests:** Auto-reply if confidence ≥ 0.80 + 20+ prior approvals in room

Default threshold 0.75 can be overridden per room after graduation (20+ reviews, >90% approval).

## Dual-Layer Drafting

### Tier 1: Auto-Reply Candidates
Messages where confidence ≥ threshold. Generated immediately; auto-sent only if no manager in room and room is graduated.

### Tier 2: Draft Review Queue
Messages where confidence < threshold OR from lead/manager OR in group chat. Collected in `draft_replies` table; displayed in dashboard.

**Evidence Tracking:**
Each draft includes evidence array:
- Retrieved documents (chat history, Jira tickets, code snippets)
- Confidence sub-scores (semantic match, sender awareness, historical accuracy)
- Generation timestamp

## Workflow Engine

YAML state machines (in `config/workflows/`) define multi-step automation:
- **Trigger:** event type from Redis (e.g., "chat_message", "jira_update")
- **States:** decision nodes, action nodes, approval gates
- **Actions:** send_reply, create_jira_issue, update_confluence, trigger_code_session
- **Audit Trail:** every action logged with tier (1=auto, 2=guided, 3=human-approved)

Example: `chat-to-jira.yaml` routes certain chat patterns to Jira ticket creation.

## Dashboard Features

### Home
- Real-time activity feed (last 50 events)
- Draft queue (pending review, count by status)
- Service health: postgres, redis, embedding API, matrix-listener, dashboard uptime

### Drafts
- All pending/reviewed drafts with evidence panel
- Approve/reject/edit inline
- Batch actions: approve all, reject all by room

### Twin Chat
- Conversation interface with the agent
- Queries: "Summarize my discussions about X"
- Personality: responds in Khanh's voice with memory grounding

### Settings (future)
- Persona editing (team, role, bio)
- Confidence thresholds per-room
- Knowledge source toggle (mute Jira, prioritize Confluence)

## Functional Requirements

| Req | Priority | Status | Notes |
|-----|----------|--------|-------|
| Ingest chat, Jira, GitLab, Confluence | P0 | Done | All 4 sources integrated |
| Vector search + semantic memory | P0 | Done | pgvector + Mem0 working |
| Generate contextual drafts in Khanh's voice | P1 | Done | Personality tuned via style examples |
| Auto-send low-confidence replies | P1 | Done | Confidence scoring + room modifiers |
| Dashboard draft review | P1 | Done | FastAPI + HTMX, SSE for real-time |
| Workflow engine (state machines) | P2 | Done | YAML parser + action executor |
| Matrix bridge + synapse integration | P1 | Done | mautrix-googlechat → synapse → listener |
| Code ingestion & search | P2 | Done | Tree-sitter chunking, 3 projects indexed |
| Pipeline monitoring | P3 | Planned | GitLab webhook integration |
| Jira/GitLab webhook integration | P3 | Planned | Replace polling with real-time |
| Confluence full-text search | P2 | Partial | Basic ingestion; advanced search TBD |

## Non-Functional Requirements

| Aspect | Target | Notes |
|--------|--------|-------|
| Latency (chat to draft) | <2s | Async ingestion allows near-real-time |
| Accuracy (correct context retrieval) | >90% | Evaluated on test set of 50+ queries |
| Safety (never violate never_do rules) | 100% | Enforced in prompt; auditable via audit_log |
| Uptime (dashboard + services) | 99.5% | Docker compose with health checks |
| Memory efficiency | <2GB heap | Single Python process for dashboard; services share venv |
| Cost (embeddings + LLM) | <$10/day | OpenRouter API for embeddings, Claude API for agent inference |

## Technology Stack

| Component | Tech | Details |
|-----------|------|---------|
| Memory | pgvector + Mem0 + OpenRouter API | Postgres 5433, BAAI/bge-m3 embeddings, episodic event log |
| LLM | Claude API | claude-opus for outward (quality), claude-sonnet for memory extraction |
| Bridge | Synapse + mautrix-googlechat | Matrix protocol; docker compose in ~/.mautrix-googlechat/ |
| Dashboard | FastAPI + HTMX | Python async; TailwindCSS styling; SSE for real-time updates |
| Event Bus | Redis | Pub/sub between services; 6379 default |
| Language | Python 3.13 | Async/await for I/O; type hints; services/.venv |
| Infrastructure | Docker Compose | Postgres, Redis services |

## Deployment Architecture

```
┌─────────────────────────────────────────────────────┐
│  Google Chat (MoMo workspace)                       │
└────────────────┬────────────────────────────────────┘
                 │ (Google Chat API)
┌────────────────▼────────────────────────────────────┐
│  mautrix-googlechat bridge (localhost:8090)         │
│  ~/.mautrix-googlechat/docker-compose.yml           │
└────────────────┬────────────────────────────────────┘
                 │ (Matrix federation)
┌────────────────▼────────────────────────────────────┐
│  Synapse Matrix Homeserver (localhost:8008)         │
│  ~/.mautrix-googlechat/data/ (state, rooms)         │
└────────────────┬────────────────────────────────────┘
                 │ (Matrix protocol)
┌────────────────▼────────────────────────────────────┐
│  matrix-listener (scripts/matrix-listener.py)       │
│  Subscribes to sync streams; publishes to Redis     │
└────────────────┬────────────────────────────────────┘
                 │ (Redis events)
     ┌───────────┼───────────┬───────────┐
     │           │           │           │
     ▼           ▼           ▼           ▼
┌─────────┬─────────┬─────────┬─────────┐
│ Memory  │ Agent   │ Ingestion│Workflow │
│Client   │Pipeline │ Scheduler│ Engine  │
└────┬────┴────┬────┴────┬─────┴────┬────┘
     │         │         │          │
     └────┬────┴────┬────┴────┬─────┘
          │ Postgres (5433)       │
          │ Redis (6379)          │
          │ OpenRouter API (remote)│
          └────────────────────────┘
          
          ▼
     Dashboard (FastAPI:8000)
     User-facing web UI with draft queue, twin chat
```

## Security & Privacy

### Data Handling
- All data stays on-premise (Postgres, Redis); embeddings sent to OpenRouter API (no raw chat data)
- Claude API calls include only generated context, not raw chat messages
- Ephemeral working memory (30-min TTL) — no persistent session logs
- Audit log tracks all auto-replies and approvals

### Access Control
- Dashboard authentication: TBD (env var for session token)
- Matrix bridge: secured by Synapse homeserver
- Postgres: localhost-only, no public exposure
- Redis: localhost-only, no auth (internal use only)

### Compliance
- GDPR: Chat history ingestion respects MoMo workplace agreements
- Audit trail: `audit_log` table tracks all significant actions
- Retention: Events kept for 90 days by default (configurable)

## Success Criteria

1. **Quality:** Draft approval rate >85% within 2 weeks of training on Khanh's style examples
2. **Speed:** <2s latency from chat message to draft in dashboard
3. **Safety:** Zero violations of `never_do` rules over 30-day observation period
4. **Adoption:** Khanh uses dashboard daily for draft review; auto-replies in 1+ spaces
5. **Knowledge:** Twin correctly answers 80%+ of domain questions about transaction history, payment, promotion modules

## Roadmap

### Phase 1 ✓ Memory Foundation
- pgvector + Mem0 setup, episodic event store, working memory session

### Phase 2 ✓ Knowledge Ingestion
- Chat, Jira, GitLab, Confluence ingestors; code ingestion with tree-sitter

### Phase 3 ✓ Dual-Mode Agent
- Outward pipeline with confidence scoring, inward assistant with voice tuning

### Phase 4 ✓ Workflow Engine
- YAML state machines, action executor, audit logging

### Phase 5 ✓ Dashboard
- FastAPI web UI, real-time SSE, draft review, twin chat, service health

### Phase 6 (Current) Integration & Polish
- Full code ingestion (3 projects indexed), persona tuning, webhook integration planning

### Phase 7 (Next) Advanced Features
- Jira/GitLab webhooks (replace polling), pipeline auto-monitoring, Confluence advanced search, multi-workspace support

## Unresolved Questions

- What is the desired retention policy for old events in `events` table? (Currently: 90 days, configurable)
- Should the dashboard require authentication, or trust the localhost:8000 assumption?
- How should the agent handle conflicting information across knowledge sources (e.g., Jira says resolved, code shows unresolved)?
- Should inward mode include "implement feature" capability (code generation + MR creation)?
