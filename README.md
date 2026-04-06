# openkhang

Digital twin for your work persona — integrates Google Chat, Jira, Confluence, and GitLab into an autonomous AI agent that can reply as you, manage tasks, and monitor workflows.

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
  → chunk → embed → store             ▼
                             Workflow Engine
                             (YAML state machines, audit log)
```

### Dual-Mode Agent

The agent operates in two modes:
- **Outward**: Acts AS you to colleagues in Google Chat — replies in your voice/style, grounded by RAG
- **Inward**: Acts AS your assistant via dashboard — reports, drafts, takes instructions

### Memory System

Three-layer memory powered by Mem0:
- **Semantic**: Vector search (pgvector + bge-m3) for knowledge retrieval
- **Episodic**: Append-only Postgres event log (chat messages, Jira updates, pipeline events)
- **Working**: In-memory session context with 30-min TTL

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env    # Edit with your API keys

# 2. Run onboarding
bash scripts/onboard.sh

# 3. Start the dashboard
bash scripts/run-dashboard.sh
# → http://localhost:8000

# 4. Start chat listener (background)
python3 scripts/matrix-listener.py --daemon
```

## Prerequisites

| Tool | Install | Purpose |
|------|---------|---------|
| Docker | `brew install docker` | Postgres, Redis, Synapse, mautrix bridge |
| Ollama | `brew install ollama` | Local bge-m3 embeddings (runs natively on Apple Silicon) |
| Python 3.12+ | System or brew | Memory, agent, ingestion, dashboard services |
| `jira` | `brew install ankitpokhrel/jira-cli/jira` | Jira ticket ingestion |
| `glab` | `brew install glab` | GitLab MR/pipeline ingestion |

## Services

| Service | Port | Description |
|---------|------|-------------|
| Postgres + pgvector | 5433 | Memory storage, event log, draft queue, workflow state |
| Redis | 6379 | Event bus (pub/sub between services) |
| Ollama | 11434 | bge-m3 embeddings (1024-dim, Vietnamese+English) |
| Synapse | 8008 | Matrix homeserver for Google Chat bridge |
| Dashboard | 8000 | Web UI: activity feed, draft review, health, twin chat |

## Configuration

### Persona (`config/persona.yaml`)
Defines the twin's identity, communication style, and safety rules.

### Confidence Thresholds (`config/confidence_thresholds.yaml`)
Per-room thresholds for auto-reply. Default 0.85 — all spaces start in draft mode.

### Workflows (`config/workflows/*.yaml`)
YAML state machines for cross-tool automation (e.g., chat→jira→code→pipeline).

## Plugin Skills (Claude Code)

| Type | Count | Items |
|------|-------|-------|
| Chat | 5 | chat-scan, chat-reply, chat-spaces, chat-auth, chat-listen |
| Jira | 2 | sprint-board, sprint-prioritize |
| GitLab | 3 | code-session, pipeline-watch, mr-manage |
| Confluence | 2 | confluence-search, confluence-update |
| Orchestrator | 1 | openkhang-status |

## Project Structure

```
openkhang/
├── services/
│   ├── memory/        # Mem0 + pgvector + episodic store
│   ├── ingestion/     # Chat, Jira, GitLab, Confluence ingestors
│   ├── agent/         # Dual-mode agent pipeline + LLM client
│   ├── workflow/      # YAML state machine engine
│   └── dashboard/     # FastAPI + HTMX web UI
├── config/
│   ├── persona.yaml
│   ├── confidence_thresholds.yaml
│   └── workflows/     # YAML workflow definitions
├── scripts/           # Setup, onboarding, run scripts
├── skills/            # Claude Code plugin skills
├── agents/            # Claude Code plugin agents
├── hooks/             # Claude Code plugin hooks
└── docker-compose.yml # Infrastructure services
```

## Development

```bash
# Run agent tests
services/.venv/bin/python3 -m pytest services/agent/tests/ -v

# Start dashboard with hot reload
services/.venv/bin/uvicorn services.dashboard.app:app --reload --port 8000

# Ingest chat history
services/.venv/bin/python3 services/memory/ingest-chat-history.py

# Check memory
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
