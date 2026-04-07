# Project Changelog: openkhang

## [Unreleased]

### Added
- **Request Traces observability feature** — Complete visibility into pipeline execution
  - New `TraceCollector` dataclass accumulates pipeline steps (classification, RAG, prompts, LLM calls, tool calls, confidence scoring)
  - `request_traces` database table stores mode, channel, intent, skill, action, input, room/sender context, confidence, tokens, latency, errors, and step timeline
  - All 3 skills instrumented: `OutwardReplySkill`, `InwardQuerySkill`, `SendAsKhanhSkill` record their actions
  - New `/traces` dashboard page with two-panel layout (list + detail view)
  - New API routes: `GET /api/traces` (filtered list) and `GET /api/traces/{id}` (detail with expandable steps)
  - Sidebar navigation updated with Traces link (scan-search icon)
  - Fire-and-forget trace persistence to avoid blocking request pipeline

### Changed
- `pipeline.py` now creates `TraceCollector` at entry, passes via `SkillContext`, saves after completion
- Dashboard file count increased to 20+; route count increased to 35 total

## [2026-04-06] - Initial Digital Twin Release (v0.2.0)

### Core Components
- **Memory Service** — Vector embeddings (1024-dim pgvector), semantic search, episodic event log, session cache
- **Ingestion Layer** — Real-time chat + 30min polling (Jira, GitLab, Confluence), semantic chunking, deduplication
- **Agent Pipeline** — 4-layer agentic architecture: channels → tools → skills → responses
  - Dual-mode execution: Outward (deterministic draft generation) + Inward (Claude tool_use for dynamic queries)
  - Confidence scoring with room/sender/history modifiers
  - Multi-provider LLM: Meridian proxy → Claude Max > Claude API fallback
- **Workflow Engine** — YAML state machines for multi-step automation with audit trail
- **Dashboard** — FastAPI web UI with HTMX + SSE real-time updates
  - Sidebar navigation (7 pages)
  - Draft queue with approval workflow
  - Activity feed with source filtering
  - Memory search + knowledge ingestion
  - Settings for persona, confidence, integrations
  - Health monitoring (Postgres, Redis, embedding API, matrix-listener)

### Infrastructure
- Postgres (5433) with pgvector, uuid-ossp extensions
- Redis (6379) for event pub/sub and session store
- Matrix Synapse (8008) + mautrix-googlechat bridge (8090)
- OpenRouter API for BAAI/bge-m3 embeddings
- Docker Compose orchestration

### Integrations
- Google Chat (via Matrix bridge)
- Jira Cloud REST API
- GitLab REST API + glab CLI
- Confluence REST API
- Local git repositories (3 projects)

### Security
- All external APIs use HTTPS + API key auth
- Local service network isolated (localhost only)
- No auth on Matrix Synapse (local trust boundary)
- Dashboard auth deferred to future phase

### Testing
- pytest + pytest-asyncio framework
- Coverage across all major components
- CI/CD integration ready

---

## Changelog Format

Entries follow [Keep a Changelog](https://keepachangelog.com/) conventions:
- **Added** — New features
- **Changed** — Modifications to existing features
- **Fixed** — Bug fixes
- **Removed** — Deleted features
- **Deprecated** — Features scheduled for removal
- **Security** — Vulnerability fixes

Each entry includes impact scope (e.g., "Storage: +5GB/year", "Latency: +50ms") when material.
