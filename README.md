# openkhang

Digital twin for your work persona — an AI agent that acts as you in Google Chat (outward mode) and assists you via web dashboard (inward mode). Integrates Google Chat, Jira, Confluence, GitLab, and source code into a unified memory-backed system.

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
  Jira/GitLab/Confluence       │                   │               :8000
  Source Code (git diff)       └───────┬───────────┘
                                       ▼
                              7-Layer Agent Pipeline
                         ┌──────────────────────────┐
                         │ 1. Channel Adapters       │
                         │ 2. LLM Router (haiku)     │
                         │ 3. Context Strategy       │
                         │ 4. Tool Registry          │
                         │ 5. Skill System           │
                         │ 6. Unified Agent Loop     │
                         │ 7. Response Router        │
                         └──────────────────────────┘
```

### Dual-Mode Agent

- **Outward**: Acts AS you to colleagues in Google Chat — replies in your voice/style, grounded by RAG. Learns from 114+ real style examples.
- **Inward**: Acts AS your autonomous assistant via dashboard — searches memory, uses tools proactively, takes instructions. Powered by ReAct loop (10 iterations, 120s timeout).

### Agent Pipeline

```
event → LLM Router (haiku, <500ms) → Context Strategy (parallel fetch) → Unified Loop → route
         │                              │                                  │
         ├─ regex fast-path (social)    ├─ social: no context              ├─ outward: structured JSON
         ├─ group detection (member_count) ├─ question: rag+code+sender+room  ├─ inward: ReAct tool loop
         └─ thread awareness            ├─ request: rag+sender+room+thread └─ config-driven (ModeConfig)
                                        └─ fyi: sender only
```

- LLM-based routing replaces brittle regex classification
- Group detection uses Matrix member count (not room name heuristics)
- Thread-aware: responds when you're active in a thread
- Parallel context pre-fetch reduces latency 20-30%
- Identity-first prompts empower autonomous reasoning
- Confidence modifiers configurable via YAML (no code changes)

### Behavioral Rules

- **DM + social** (hi, thanks): Auto-reply
- **DM + work question**: Confidence-gated (may draft for review)
- **Group + social/humor**: Skip (router decides via LLM)
- **Group + work/mention**: Draft for review
- **Manager/Lead sender**: Always draft
- **Thread you're in**: Always respond
- **Room with no history**: Skip

### LLM Providers

**Meridian** (Claude Max subscription proxy, $0 marginal cost) powers agent replies AND memory extraction (haiku via OpenAI-compatible endpoint). Falls back to Claude API if unavailable.

### Memory System

Three-layer memory powered by Mem0 + Haiku 4.5 (via Meridian):
- **Semantic**: Vector search (pgvector + bge-m3 via OpenRouter API)
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

### LLM (`.env`)

```bash
# Meridian proxy (Claude Max subscription, $0 marginal cost)
MERIDIAN_URL=http://127.0.0.1:3456

# Fallback — Claude API (paid per-token)
ANTHROPIC_API_KEY=sk-ant-...

# Embeddings — OpenRouter API (BAAI/bge-m3)
EMBEDDING_API_KEY=sk-or-...
EMBEDDING_API_URL=https://openrouter.ai/api/v1
EMBEDDING_MODEL=BAAI/bge-m3
```

### Persona (`config/persona.yaml`)
Twin's identity, communication style, safety rules. Edits take effect on next message — no restart needed.

### Confidence (`config/confidence_thresholds.yaml`)
Per-room thresholds and scoring modifiers. All modifiers are YAML-configurable:
```yaml
default_threshold: 0.75
modifiers:
  many_memories: 0.10      # bonus: 3+ grounding memories
  deadline_risk: -0.20     # penalty: timeline questions
  unknown_sender: -0.15    # penalty: no prior interactions
  social_dm: 0.25          # bonus: social in DM
  group_social_skip: -0.90 # penalty: social in group
  no_history: -0.90        # penalty: no room history
  cautious_sender: -0.30   # penalty: manager/lead sender
  high_priority_boost: 0.15
  low_priority_penalty: -0.10
```

### Projects (`config/projects.yaml`)
Source code repositories for knowledge ingestion.

### Workflows (`config/workflows/*.yaml`)
YAML state machines for cross-tool automation (chat→jira→code→pipeline).

## Project Structure

```
openkhang/
├── services/
│   ├── memory/           # Mem0 + pgvector + episodic store
│   ├── ingestion/        # Chat, Jira, GitLab, Confluence, Code ingestors
│   ├── agent/            # 7-layer agent pipeline
│   │   ├── llm_router.py         # LLM-based routing (haiku + regex fallback)
│   │   ├── context_strategy.py   # Parallel context pre-fetch per intent
│   │   ├── agent_loop.py         # Unified execution (config-driven modes)
│   │   ├── pipeline.py           # Main orchestrator
│   │   ├── classifier.py         # Regex fallback classifier
│   │   ├── confidence.py         # Config-driven confidence scoring
│   │   ├── prompt_builder.py     # System + user message assembly
│   │   ├── llm_client.py         # Multi-provider (Meridian → Claude API)
│   │   ├── tool_calling_loop.py  # ReAct loop (10 iters, 120s timeout)
│   │   ├── tool_registry.py      # Tool discovery + execution
│   │   ├── skill_registry.py     # Skill matching + delegation
│   │   ├── tools/                # 8 tool wrappers
│   │   ├── skills/               # 3 skills (outward, inward, send-as-owner)
│   │   ├── prompts/              # System prompts + router prompt
│   │   ├── channel_adapter*.py   # Channel normalization (Matrix, Dashboard, Telegram)
│   │   ├── response_router.py    # Response routing by channel
│   │   └── tests/                # 175 tests (router, context, loop, integration)
│   ├── workflow/         # YAML state machine engine + audit log
│   └── dashboard/        # FastAPI + HTMX + SSE (inbox/agent relay)
├── config/
│   ├── persona.yaml                  # Twin identity + style
│   ├── projects.yaml                 # Code repos to index
│   ├── confidence_thresholds.yaml    # Thresholds + modifiers
│   ├── style_examples.jsonl          # Real sent messages (few-shot)
│   └── workflows/                    # YAML workflow definitions
├── scripts/
│   ├── onboard.sh                    # First-time setup
│   ├── setup-bridge.sh               # Synapse + mautrix bridge
│   ├── setup-memory.sh               # Postgres + Redis
│   ├── run-dashboard.sh              # Start web UI
│   ├── matrix-listener.py            # Real-time chat listener
│   ├── seed-code.py                  # Index source code
│   ├── seed-knowledge.py             # Seed Jira/GitLab/chat
│   └── full-chat-seed.py             # Full Matrix history sync
├── docs/              # Project documentation (7 files)
├── plans/             # Implementation plans + reports
└── docker-compose.yml # Infrastructure (Postgres, Redis)
```

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

## Development

```bash
# Run tests (175 passing)
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
