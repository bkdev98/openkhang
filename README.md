# openkhang

Digital twin for your work persona — an AI agent that acts as you in Google Chat (outward mode) and assists you via a web dashboard (inward mode). Integrates Google Chat, Jira, Confluence, GitLab, and your source code into a unified memory-backed system.

## Architecture

```
Google Chat ←→ mautrix bridge ←→ Synapse ←→ matrix-listener
                                                   │
                                             Redis event bus
                                                   │
             ┌─────────────────┬───────────────────┼───────────────────┐
             ▼                 ▼                   ▼                   ▼
       Knowledge          Mem0 + pgvector    Dual-Mode Agent      Dashboard
       Ingestion          (Memory Layer)     (Outward/Inward)   (FastAPI+HTMX)
       Pipeline                │                   │               :8000
  Jira/GitLab/Confluence       └───────┬───────────┘
  Source Code (git diff)               ▼
  → chunk → embed → store    Workflow Engine
                             (YAML state machines, audit log)
```

### Dual-Mode Agent

- **Outward**: Acts AS you to colleagues in Google Chat — replies in your voice/style, grounded by RAG. Learns from 114+ real style examples.
- **Inward**: Acts AS your assistant via dashboard — reports, drafts, takes instructions. Can search your codebase.

### Behavioral Rules

- **DM + social** (hi, thanks): Auto-reply
- **DM + work question**: Confidence-gated (may draft for review)
- **Group + social/humor**: Skip (Khanh doesn't reply to group banter)
- **Group + work/mention**: Draft for review
- **Manager/Lead sender**: Always draft
- **Room with no history**: Skip (only reply where you've chatted before)

### LLM Providers

**Meridian** (Claude Max subscription proxy, $0 marginal cost) powers two things: agent replies AND memory extraction (claude-haiku-4-5-20251001 via OpenAI-compatible endpoint). Meridian auto-starts with the dashboard — no separate terminal needed.

### Memory System

Three-layer memory powered by Mem0 + Haiku 4.5 (via Meridian):
- **Semantic**: Vector search (pgvector + bge-m3 via OpenRouter API) for knowledge retrieval
- **Episodic**: Append-only Postgres event log (chat, code, Jira, agent actions)
- **Working**: In-memory session context with 30-min TTL

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env    # Set MERIDIAN_URL + work tool creds

# 2. Run onboarding (checks prereqs, starts infra, pulls bge-m3)
bash scripts/onboard.sh

# 3. Set up Google Chat bridge (first time only)
bash scripts/setup-bridge.sh

# 4. Start chat listener
python3 scripts/matrix-listener.py --daemon

# 5. Seed knowledge (chat style, Jira, code)
services/.venv/bin/python3 scripts/full-chat-seed.py
services/.venv/bin/python3 scripts/seed-knowledge.py --source jira
services/.venv/bin/python3 scripts/seed-code.py

# 6. Start the dashboard (includes agent relay + Meridian proxy + ingestion)
bash scripts/run-dashboard.sh
# → http://localhost:8000
```

## Prerequisites

| Tool | Install | Purpose |
|------|---------|---------|
| Docker | `brew install docker` | Postgres, Redis, Synapse, mautrix bridge |
| Python 3.12+ | System or brew | All services run in `services/.venv` |
| Node.js 18+ | `brew install node` | Meridian proxy runtime |
| Meridian | `npm install -g @rynfar/meridian` | Claude Max subscription proxy |
| `jira` | `brew install ankitpokhrel/jira-cli/jira` | Jira ticket ingestion (optional) |
| `glab` | `brew install glab` | GitLab MR ingestion (optional) |

## Services

| Service | Port | Description |
|---------|------|-------------|
| Meridian | 3456 | Claude Max subscription proxy (auto-started with dashboard) |
| Postgres + pgvector | 5433 | Memory, events, drafts, workflows |
| Redis | 6379 | Event bus (pub/sub) |
| OpenRouter API | — | bge-m3 embeddings via BAAI/bge-m3 (OpenAI-compatible, remote) |
| Synapse | 8008 | Matrix homeserver for Google Chat bridge |
| Dashboard | 8000 | Web UI: feed, drafts, health, twin chat |

## Configuration

### LLM (`env`)

```bash
# Meridian proxy (Claude Max subscription, $0 marginal cost)
# Powers TWO things: agent replies AND memory extraction (claude-haiku-4-5-20251001)
# Auto-starts with dashboard if set. Falls back to ANTHROPIC_API_KEY if not set.
MERIDIAN_URL=http://127.0.0.1:3456

# Fallback only — Claude API (paid per-token, used if MERIDIAN_URL is not set)
ANTHROPIC_API_KEY=sk-ant-...

# Embeddings — OpenRouter API (OpenAI-compatible, BAAI/bge-m3)
EMBEDDING_API_KEY=sk-or-...
EMBEDDING_API_URL=https://openrouter.ai/api/v1   # default
EMBEDDING_MODEL=BAAI/bge-m3                       # default
```

### Persona (`config/persona.yaml`)
Twin's identity, communication style, safety rules. **Edits take effect on next message** — no restart needed.

### Projects (`config/projects.yaml`)
Source code repositories for knowledge ingestion. Business logic docs and API specs are prioritized.

### Confidence (`config/confidence_thresholds.yaml`)
Per-room thresholds for auto-reply. Default 0.75. Group chat work messages always go to draft.

### Workflows (`config/workflows/*.yaml`)
YAML state machines for cross-tool automation (chat→jira→code→pipeline).

## Knowledge Sources

| Source | Method | Frequency |
|--------|--------|-----------|
| Chat messages | Tail JSONL → events | Real-time |
| Chat → agent | Poll events → pipeline | ~3s |
| Jira tickets | jira-cli poll | Every 5 min |
| GitLab MRs | glab poll | Every 5 min |
| Confluence | REST API poll | Every 1 hour |
| Source code | `git diff` incremental | Every 10 min |
| Style examples | Matrix full-history sync | On-demand |

## Project Structure

```
openkhang/
├── services/
│   ├── memory/        # Mem0 + pgvector + episodic store
│   ├── ingestion/     # Chat, Jira, GitLab, Confluence, Code ingestors
│   ├── agent/         # Dual-mode pipeline, LLM client, confidence scorer
│   ├── workflow/      # YAML state machine engine + audit log
│   └── dashboard/     # FastAPI + HTMX + SSE (inbox/agent relay)
├── config/
│   ├── persona.yaml            # Twin identity + style
│   ├── projects.yaml           # Code repos to index
│   ├── confidence_thresholds.yaml
│   ├── style_examples.jsonl    # Your real sent messages (few-shot)
│   └── workflows/              # YAML workflow definitions
├── scripts/
│   ├── onboard.sh              # First-time setup
│   ├── setup-bridge.sh         # Synapse + mautrix bridge
│   ├── setup-memory.sh         # Postgres + Redis
│   ├── run-dashboard.sh        # Start web UI
│   ├── matrix-listener.py      # Real-time chat listener
│   ├── seed-code.py            # Index source code
│   ├── seed-knowledge.py       # Seed Jira/GitLab/chat
│   └── full-chat-seed.py       # Full Matrix history sync
├── archive/           # Claude Code plugin (skills, agents, hooks) — reference only
├── docs/              # Project documentation (7 files)
├── plans/             # Implementation plans + reports
└── docker-compose.yml # Infrastructure (Postgres, Redis)
```

## Development

```bash
# Run tests (78 passing)
services/.venv/bin/python3 -m pytest services/agent/tests/ -v

# Dashboard with hot reload
services/.venv/bin/uvicorn services.dashboard.app:app --reload --port 8000

# Seed code (incremental — only changed files)
services/.venv/bin/python3 scripts/seed-code.py

# Check DB stats
docker compose exec -T postgres psql -U openkhang -d openkhang \
  -c "SELECT source, count(*) FROM events GROUP BY source ORDER BY count DESC;"

# Search memory
services/.venv/bin/python3 -c "
import asyncio
from dotenv import load_dotenv; load_dotenv()
from services.memory.config import MemoryConfig
from services.memory.client import MemoryClient
async def q():
    c = MemoryClient(MemoryConfig.from_env()); await c.connect()
    r = await c.search('your query here'); print(r); await c.close()
asyncio.run(q())
"
```

## Documentation

Full docs in `docs/`:
- [Project Overview](docs/project-overview-pdr.md) — Vision, requirements, success criteria
- [System Architecture](docs/system-architecture.md) — Components, data flow, security
- [Code Standards](docs/code-standards.md) — Python conventions, testing
- [Codebase Summary](docs/codebase-summary.md) — Directory tree, modules, schema
- [Deployment Guide](docs/deployment-guide.md) — Setup, troubleshooting
- [Project Roadmap](docs/project-roadmap.md) — Phases, timeline, backlog
