# Codebase Summary: openkhang

**Last Updated:** April 7, 2026  
**Total Files:** 135+  
**Total Tokens:** ~180,000  
**Main Language:** Python 3.13

## Directory Structure Overview

```
openkhang/
├── services/                      # Core Python services (shared .venv)
│   ├── memory/                    # Vector search + episodic store (8 files)
│   ├── ingestion/                 # Knowledge source ingestors (10 files)
│   ├── agent/                     # Dual-mode agent pipeline (15 files)
│   ├── workflow/                  # YAML state machines (5 files)
│   ├── dashboard/                 # FastAPI web UI (11 files)
│   └── requirements.txt           # Shared dependencies
│
├── config/                        # Configuration files (YAML + JSON)
│   ├── persona.yaml               # Identity, style, constraints
│   ├── confidence_thresholds.yaml # Per-room thresholds
│   ├── projects.yaml              # Code projects to index
│   ├── style_examples.jsonl       # Chat examples for tuning
│   └── workflows/                 # YAML state machine definitions
│
├── scripts/                       # Setup & ingestion scripts (8 files)
│   ├── onboard.sh                 # Full setup orchestrator
│   ├── setup-bridge.sh            # Bridge + Synapse setup
│   ├── setup-memory.sh            # Memory service initialization
│   ├── run-dashboard.sh           # Start web UI
│   ├── matrix-listener.py         # Chat listener daemon
│   ├── seed-knowledge.py          # Ingest initial data
│   ├── seed-code.py               # Index source code
│   └── full-chat-seed.py          # Bulk chat history import
│
├── agents/                        # Claude Code plugin agents (4 files)
│   ├── bug-investigator.md        # Investigate urgent bugs
│   ├── chat-categorizer.md        # Categorize chat patterns
│   ├── sprint-monitor.md          # Track sprint progress
│   └── pipeline-fixer.md          # Auto-fix CI/CD failures
│
├── skills/                        # Claude Code plugin skills (13 dirs)
│   ├── chat-autopilot/            # Main chat interaction
│   ├── chat-scan/                 # Search chat history
│   ├── chat-reply/                # Draft replies
│   ├── chat-spaces/               # List spaces
│   ├── chat-auth/                 # Authentication
│   ├── chat-listen/               # Listen for messages
│   ├── jira-knowledge/            # Jira integration
│   ├── jira-knowledge/references/ # Jira CLI reference
│   ├── gitlab-knowledge/          # GitLab integration
│   ├── confluence-search/         # Confluence search
│   ├── confluence-update/         # Update Confluence
│   ├── pipeline-watch/            # Monitor pipelines
│   ├── mr-manage/                 # Manage MRs
│   ├── sprint-board/              # Sprint board view
│   ├── code-session/              # Code implementation
│   └── openkhang-status/          # System status
│
├── hooks/                         # Claude Code plugin hooks (2 files)
│   ├── hooks.json                 # Hook definitions
│   └── scripts/                   # Hook scripts
│
├── plans/                         # Development plans & reports
│   ├── 260406-1153-digital-twin-system/
│   │   ├── plan.md                # Overall plan
│   │   ├── phase-01-*.md          # Memory foundation
│   │   ├── phase-02-*.md          # Knowledge ingestion
│   │   ├── phase-03-*.md          # Dual-mode agent
│   │   ├── phase-04-*.md          # Workflow engine
│   │   ├── phase-05-*.md          # Dashboard
│   │   ├── phase-06-*.md          # Integration
│   │   └── reports/               # Phase completion reports
│   └── reports/                   # Researcher findings
│
├── .claude/                       # Claude Code configuration
│   ├── openkhang.local.md         # Project instructions
│   ├── gchat-autopilot.local.md   # Chat autopilot rules
│   └── ...
│
├── docker-compose.yml             # Infrastructure services
├── .env.example                   # Configuration template
├── .gitignore
├── README.md
└── docs/                          # This documentation (NEW)
    ├── project-overview-pdr.md    # Vision & requirements
    ├── system-architecture.md     # Component design
    ├── code-standards.md          # Coding conventions
    ├── codebase-summary.md        # This file
    ├── deployment-guide.md        # Setup instructions
    └── project-roadmap.md         # Progress & timeline
```

## Key Services

### 1. Memory Service (`services/memory/`)

**Purpose:** Vector embeddings + episodic event log + session state

**Files (8 total, ~1100 LOC):**
- `client.py` (220 LOC) — Public API: `MemoryClient` class with search, add_memory, get_entity
- `config.py` (95 LOC) — Load `.env` vars, initialize Mem0/embedding config
- `episodic.py` (180 LOC) — Append-only event log; `events` table interface
- `working.py` (80 LOC) — In-memory TTL cache; `WorkingMemory` class
- `schema.sql` (84 LOC) — Postgres schema: extensions, tables, indexes
- `ingest-chat-history.py` (140 LOC) — One-off bulk import from chat export
- `__init__.py` — Package init
- `tests/` — Unit tests

**Key Classes:**
```python
class MemoryClient:
    async def search(query: str, top_k: int = 5) -> List[Dict]
    async def add_memory(memory_text: str, metadata: Dict, source: str)
    async def search_entity(entity_type: str) -> List[Entity]
    async def delete_memory(memory_id: str)

class EpisodicStore:
    async def append_event(source: str, event_type: str, payload: Dict)
    async def get_recent_events(source: Optional[str], limit: int = 50)
    async def search_events(query: str, date_range: Tuple)

class WorkingMemory:
    def get_session(session_id: str) -> Optional[Session]
    def set_session(session_id: str, data: Dict, ttl: int = 1800)
    def clear_expired()
```

**Database:**
- `pgvector` extension (1024-dim vectors)
- `uuid-ossp` extension (for UUIDs)
- Tables: `events`, `sync_state` (openkhang-owned); `mem0_memories`, etc (Mem0-managed)

### 2. Ingestion Layer (`services/ingestion/`)

**Purpose:** Fetch data from 4 sources, chunk semantically, embed, store

**Files (10 total, ~1800 LOC):**
- `base.py` (140 LOC) — `BaseIngestor` abstract class, retry logic
- `chat.py` (250 LOC) — `ChatIngestor`, real-time via matrix-listener
- `jira.py` (280 LOC) — `JiraIngestor`, 30-min polling via REST API
- `gitlab.py` (240 LOC) — `GitLabIngestor`, 30-min polling via glab CLI
- `confluence.py` (310 LOC) — `ConfluenceIngestor`, 1h polling via REST API
- `code.py` (380 LOC) — `CodeIngestor`, tree-sitter chunking for 3 projects
- `chunker.py` (140 LOC) — `SemanticChunker` (paragraph/function/class splitting)
- `entity.py` (95 LOC) — `Entity` dataclass (name, type, description)
- `scheduler.py` (225 LOC) — `IngestScheduler`, coordinates polling schedule
- `sync_state.py` (95 LOC) — `SyncState` tracker (prevents duplicate ingestion)

**Key Classes:**
```python
class ChatIngestor(BaseIngestor):
    async def ingest_message(msg: Message, room: Room)
    async def search_history(query: str, room_id: Optional[str])

class JiraIngestor(BaseIngestor):
    async def ingest_issue(issue_id: str, full: bool = False)
    async def search_issues(jql: str, limit: int = 10)
    async def poll_recently_updated(limit: int = 50)

class CodeIngestor(BaseIngestor):
    async def ingest_repo(project_key: str, force: bool = False)
    async def search_code(query: str, file_type: Optional[str])
    async def index_function(func_name: str, file_path: str, source: str)

class IngestScheduler:
    async def start()
    async def stop()
    def register_ingestor(ingestor: BaseIngestor, schedule: str)
```

**Config (`config/projects.yaml`):**
- 3 projects: momo-app (Kotlin), transactionhistory (Kotlin+TS), expense (Kotlin+TS)
- Include/exclude patterns, file extensions, max file size

**Integration with Memory:**
All ingestors call `MemoryClient.add_memory()` after chunking.

### 3. Agent Pipeline & Skill System (`services/agent/`)

**Purpose:** 7-layer agentic architecture: router → context → channels → tools → loop → skills → responses

**Files (52 total, ~7200 LOC):**

**Core Orchestration (7 files, ~1350 LOC):**
- `pipeline.py` (264 LOC) — Main orchestrator; matches skills via registry, creates trace per request
- `classifier.py` (165 LOC) — `MessageClassifier`, 6-class classification
- `confidence.py` (255 LOC) — `ConfidenceScorer`, base + room/sender/history modifiers
- `prompt_builder.py` (280 LOC) — `PromptBuilder`, system + RAG context + user
- `llm_client.py` (300 LOC) — `LLMClient`, multi-provider (Meridian > Claude API)
- `draft_queue.py` (225 LOC) — `DraftQueue`, pending → approved → sent workflow
- `trace_collector.py` (130 LOC) — `TraceCollector`, accumulates steps (RAG, prompts, LLM, tools) for observability

**Layer 1: Message Routing (2 files, ~200 LOC):**
- `llm_router.py` (150 LOC) — LLM-based message router with regex fast-path
- `prompts/router_prompt.md` (50 LOC) — Router system prompt template

**Layer 2: Context Strategy (2 files, ~250 LOC):**
- `context_strategy.py` (250 LOC) — Parallel context fetching per intent, ContextBundle dataclass

**Layer 3: Channel Adapters (6 files, ~569 LOC):**
- `channel_adapter.py` (115 LOC) — `ChannelAdapter` ABC, `CanonicalMessage` dataclass
- `matrix_channel_adapter.py` (166 LOC) — Matrix (Google Chat) bridge adapter
- `mention_detector.py` (79 LOC) — Mention detection: `strip_diacritics()`, `get_mention_patterns()`, `detect_mention()`
- `dashboard_channel_adapter.py` (85 LOC) — Web dashboard (twin chat) adapter
- `telegram_channel_adapter.py` (25 LOC) — Telegram adapter stub
- `response_router.py` (85 LOC) — `ResponseRouter`, dispatch by channel

**Layer 4: Tool Registry & Tools (9 files, ~900 LOC):**
- `tool_registry.py` (85 LOC) — `BaseTool` ABC, `ToolRegistry` with execution
- `tools/` directory (8 files, ~800 LOC total):
  * `search_knowledge_tool.py` (50 LOC) — Query semantic memory
  * `search_code_tool.py` (85 LOC) — Search code repositories (extract terms)
  * `get_sender_context_tool.py` (40 LOC) — Sender role/history context
  * `get_room_history_tool.py` (40 LOC) — Room message history
  * `send_message_tool.py` (50 LOC) — Send message to channel
  * `lookup_person_tool.py` (40 LOC) — Find person by name
  * `create_draft_tool.py` (60 LOC) — Create draft reply
  * `__init__.py` (15 LOC) — Tool re-exports

**Layer 5: Unified Agent Loop (1 file, ~200 LOC):**
- `agent_loop.py` (200 LOC) — Config-driven execution loop (outward+inward), ModeConfig dataclass

**Layer 6: Skill System (5 files, ~1500 LOC):**
- `skill_registry.py` (100 LOC) — `BaseSkill` ABC, `SkillRegistry`, deterministic matching
- `skills/` directory (4 files, ~1400 LOC total):
  * `outward_reply_skill.py` (300 LOC) — Deterministic draft generation (safety-first)
  * `inward_query_skill.py` (280 LOC) — Claude tool_use for dynamic tool selection
  * `send_as_khanh_skill.py` (200 LOC) — Execute approved draft send action
  * `skill_helpers.py` (100 LOC) — Shared skill utilities

**Layer 7: Tool-Calling Loop (1 file, ~150 LOC):**
- `tool_calling_loop.py` (150 LOC) — ReAct loop for Claude tool_use (inward mode only)

**Prompts & Config:**
- `prompts/outward_system.md` — System prompt for outward mode
- `prompts/inward_system.md` — System prompt for inward (assistant) mode
- `prompts/` — Other prompt templates

**Tests:**
- `tests/` (8 files, ~1200 LOC) — Unit tests for all components

**Key Classes:**
```python
# Channel Adapters
class ChannelAdapter(ABC):
    async def normalize_inbound(payload: dict) -> CanonicalMessage
    async def send_outbound(result: AgentResult, msg: CanonicalMessage) -> str | None

class ResponseRouter:
    def register(channel: str, adapter: ChannelAdapter)
    async def dispatch(result: AgentResult, msg: CanonicalMessage) -> str | None

# Tools
class BaseTool(ABC):
    @property name() -> str
    @property description() -> str
    @property parameters() -> dict  # JSON Schema
    async def execute(**kwargs) -> ToolResult

class ToolRegistry:
    def register(tool: BaseTool)
    async def execute(tool_name: str, **kwargs) -> ToolResult
    def list_descriptions() -> list[dict]  # For Claude tool_use

# Skills
class BaseSkill(ABC):
    @property name() -> str
    @property match_criteria() -> dict  # {mode, intent, body_pattern}
    async def execute(event: dict, tools, llm, context: SkillContext) -> Any

class SkillRegistry:
    def register(skill: BaseSkill)
    def match(mode: str, intent: str, body: str = "") -> BaseSkill | None

# Core Components
class MessageClassifier:
    async def classify(msg: Message) -> str  # "work"|"question"|etc

class ConfidenceScorer:
    async def score(response: str, msg: Message, context: List) -> float

class DraftQueue:
    async def enqueue(draft: DraftReply)
    async def get_pending(room_id: Optional[str]) -> List[DraftReply]
    async def approve(draft_id: str, edited_text: Optional[str])
```

**Pipeline Flow (Skill-Driven):**
1. ChannelAdapter normalizes inbound → CanonicalMessage
2. SkillRegistry matches mode+intent+body → BaseSkill
3. Skill executes (calls tools, LLM, classifier, scorer as needed)
4. ResponseRouter dispatches AgentResult to adapter
5. Adapter sends via Matrix/Dashboard/Telegram/etc

**Config:**
- `config/persona.yaml` — Identity, style, never_do rules
- `config/confidence_thresholds.yaml` — Per-room thresholds

### 4. Workflow Engine (`services/workflow/`)

**Purpose:** YAML state machines for multi-step automation with audit trail

**Files (5 total, ~800 LOC):**
- `workflow_engine.py` (390 LOC) — Main orchestrator; manage instances
- `action_executor.py` (285 LOC) — Execute actions (send_reply, create_jira, etc)
- `state_machine.py` (165 LOC) — YAML parser, state transitions
- `workflow_persistence.py` (130 LOC) — Load/save from Postgres
- `audit_log.py` (115 LOC) — Record actions + approvals

**Key Classes:**
```python
class WorkflowEngine:
    async def start_workflow(name: str, trigger_event: Dict) -> str
    async def get_instance(instance_id: str) -> WorkflowInstance
    async def cancel_workflow(instance_id: str)

class StateMachine:
    def __init__(self, yaml_path: str)
    def get_current_state() -> State
    async def transition(action: str)
    def validate()

class ActionExecutor:
    async def execute(action_type: str, params: Dict, tier: int) -> Dict
    # Actions: send_reply, create_jira, update_confluence, trigger_code_session
```

**Workflow Examples (`config/workflows/`):**
- `chat-to-jira.yaml` — Route chat patterns to Jira ticket creation
- `pipeline-failure.yaml` — Auto-investigate failed CI/CD builds

**Three-Tier Autonomy:**
- Tier 1: Auto-execute (no approval)
- Tier 2: Guided (show preview before executing)
- Tier 3: Human-only (must be manually approved)

**Audit Trail:**
Every action logged to `audit_log` table with: workflow_id, action_type, tier, params, result, approved_by, created_at.

### 5. Dashboard (`services/dashboard/`)

**Purpose:** Web UI for draft review, service health, twin chat, memory management, request traces, settings

**Files (20+ total, ~2800 LOC):**
- `app.py` (280 LOC) — FastAPI main app, 33 routes, page rendering with HTMX support
- `api_routes.py` (150 LOC) — API endpoint logic (extracted from app.py)
- `dashboard_services.py` (355 LOC) — High-level service: drafts, hourly stats, events, memory ops
- `memory_services.py` (120 LOC) — Mem0 search, delete, text/file ingest
- `settings_services.py` (95 LOC) — YAML read/write for persona, confidence, projects
- `inbox_relay.py` (95 LOC) — Consolidate mentions/assignments/flags
- `agent_relay.py` (160 LOC) — Direct agent communication
- `health_checker.py` (110 LOC) — Probe postgres, redis, embedding API, matrix-listener
- `twin_chat.py` (75 LOC) — Conversation persistence, history retrieval
- `templates/base.html` (180 LOC) — Sidebar layout, main content shell, HTMX routing
- `templates/pages/` (7 new files, ~900 LOC total):
  * `overview.html` — Stats, recent drafts, live activity
  * `activity.html` — Full activity log with source filters, infinite scroll
  * `chat.html` — Conversation UI, message bubbles, markdown
  * `drafts.html` — Tab bar (Pending/Approved/Rejected), search, history
  * `memory.html` — Memory search, type filters, knowledge drop form
  * `traces.html` — Request traces with mode/action filters, two-panel detail view
  * `settings.html` — Persona, confidence, projects, integrations
- `templates/partials/` (5+ new files, ~400 LOC total):
  * `sidebar.html` — Nav items with icons, health footer, auto-reply toggle
  * `stat_card.html` — Stat with sparkline SVG
  * `activity_card.html` — Event card with source icon, time-ago, expandable details
  * `chat_bubble.html` — User vs twin message bubbles with confidence/latency
  * `draft_card.html` — Draft with confidence badge, approve/reject/edit actions
  * `memory_card.html` — Memory entry with type badge, source, delete button
- `templates/static/style.css` (280 LOC) — Warm terminal theme, sidebar styles, animations, responsive

**Key Routes (35 total):**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Redirect to /pages/overview |
| GET | `/pages/{name}` | Render page (partial or full) |
| GET | `/api/stats/hourly` | Hourly event counts for sparklines |
| GET | `/api/feed` (SSE) | Real-time activity stream |
| GET | `/api/feed/history` | Paginated events with source filter |
| GET | `/api/drafts` | List drafts (status/search/pagination) |
| POST | `/api/drafts/{id}/approve` | Approve draft |
| POST | `/api/drafts/{id}/reject` | Reject draft |
| POST | `/api/drafts/{id}/edit` | Edit and re-send |
| GET | `/api/traces` | List traces (mode/action filters, pagination) |
| GET | `/api/traces/{trace_id}` | Trace detail with expandable steps |
| GET | `/api/chat/history` | Conversation history |
| POST | `/api/chat` | Query agent |
| POST | `/api/chat/clear` | Clear conversation |
| GET | `/api/memory/search` | Search memories |
| DELETE | `/api/memory/{id}` | Delete memory |
| POST | `/api/memory/ingest` | Ingest text or file |
| GET | `/api/settings/{section}` | Get settings |
| POST | `/api/settings/{section}` | Save settings |
| POST | `/api/settings/test-connection` | Test integration |
| GET | `/health` | Service health |

**New Features:**
- Sidebar navigation (7 pages)
- Overview: stats with 24h sparklines, recent drafts, live feed
- Activity: readable event cards with source icons, infinite scroll
- Chat: conversation UI with markdown, history, typing indicator
- Drafts: tabs (Pending/Approved/Rejected), search, historical records
- Traces: observability for pipeline steps (RAG, prompts, LLM, tools) with mode/action filters
- Memory: search/delete Mem0 entries, knowledge drop form (text/pdf/md)
- Settings: persona, confidence thresholds, projects, integrations
- Real-time: SSE for activity + HTMX for page navigation

**Frontend Architecture:**
- HTMX 1.9: page routing without full reloads, auto-scroll, intersect
- Jinja2: base + 6 pages + 6 partials + 1 sidebar
- TailwindCSS: warm charcoal palette (ok-void, ok-srf, ok-raised, etc.)
- Lucide Icons: source icons (chat, jira, gitlab, confluence)
- marked.js: markdown rendering in chat
- Vanilla JS: time-ago formatter, auto-scroll, drag-and-drop file upload

## Database Schema

**Postgres (5433)**

```sql
-- Episodic event log (append-only)
CREATE TABLE events (
    id UUID PRIMARY KEY,
    source VARCHAR(50),           -- 'chat'|'jira'|'gitlab'|'confluence'
    event_type VARCHAR(100),       -- 'message.new'|'issue.created'|'mr.updated'|etc
    actor VARCHAR(255),            -- User who triggered event
    payload JSONB NOT NULL,        -- Raw event data
    metadata JSONB DEFAULT '{}',   -- Tags, room_id, project_id, etc
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_events_source, idx_events_created_at, idx_events_type;

-- Draft replies queue
CREATE TABLE draft_replies (
    id UUID PRIMARY KEY,
    event_id UUID REFERENCES events(id),
    room_id VARCHAR(255),
    original_message TEXT,
    draft_text TEXT,
    confidence FLOAT,              -- 0.0 - 1.0
    evidence JSONB,                -- Retrieved docs, scores
    status VARCHAR(20),            -- 'pending'|'approved'|'rejected'|'edited'
    created_at TIMESTAMPTZ,
    reviewed_at TIMESTAMPTZ,
    reviewer_action VARCHAR(20)
);
Create INDEX idx_drafts_status, idx_drafts_room;

-- Ingestion sync state
CREATE TABLE sync_state (
    source VARCHAR(50) PRIMARY KEY,  -- 'chat'|'jira'|'gitlab'|'confluence'
    last_synced_at TIMESTAMPTZ,
    item_count INTEGER
);

-- Workflow instances
CREATE TABLE workflow_instances (
    id UUID PRIMARY KEY,
    workflow_name VARCHAR(100),
    current_state VARCHAR(100),
    context JSONB,
    trigger_event JSONB,
    status VARCHAR(20),            -- 'active'|'completed'|'failed'
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

-- Audit log (action trail)
CREATE TABLE audit_log (
    id UUID PRIMARY KEY,
    workflow_id UUID REFERENCES workflow_instances(id),
    action_type VARCHAR(100),
    tier INTEGER,                  -- 1|2|3 (autonomy level)
    params JSONB,
    result JSONB,
    approved_by VARCHAR(255),
    created_at TIMESTAMPTZ
);

-- Request traces (observability)
CREATE TABLE request_traces (
    id UUID PRIMARY KEY,
    mode VARCHAR(50),              -- 'outward'|'inward'|'send'
    channel VARCHAR(50),           -- 'matrix'|'dashboard'|'telegram'
    intent VARCHAR(100),           -- Classification: work|question|social|etc
    skill VARCHAR(100),            -- Matched skill name
    action VARCHAR(100),           -- Specific action taken
    input_body TEXT,               -- Input message text (truncated)
    room_id VARCHAR(255),
    sender_id VARCHAR(255),
    confidence FLOAT,              -- 0.0 - 1.0 (outward mode only)
    tokens INTEGER,                -- LLM tokens used
    latency FLOAT,                 -- Total request time (seconds)
    error TEXT,                    -- Error message if failed
    steps JSONB,                   -- Array of trace steps with timestamps
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_request_traces_created, idx_request_traces_mode, idx_request_traces_action;

-- Mem0-managed tables (auto-created)
CREATE TABLE mem0_memories (
    id UUID PRIMARY KEY,
    text TEXT,
    embedding VECTOR(1024),        -- pgvector
    metadata JSONB,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);
```

## External Integrations

| Service | Integration | Usage |
|---------|-----------|-------|
| Google Chat | mautrix-googlechat bridge | Receive/send messages |
| Jira | REST API + jira CLI | Ingest issues, create tickets |
| GitLab | glab CLI + REST API | Ingest MRs, trigger pipelines |
| Confluence | REST API | Ingest pages, update docs |
| Meridian | @rynfar/meridian (localhost:3456) | Claude Max subscription proxy for agent replies |
| Claude API | anthropic Python SDK (fallback) | Generate responses if Meridian unavailable |
| OpenRouter API | BAAI/bge-m3 (remote) | Embeddings (1024-dim) |
| Postgres | psycopg + pgvector | Memory, events, drafts, workflows |
| Redis | aioredis | Pub/sub event bus, session store |
| Matrix | Matrix Client API | Send messages to rooms |

## Key Dependencies

```python
# From services/requirements.txt
python-dotenv==1.0.0
pydantic==2.5.0
psycopg[binary]==3.1.12
pgvector==0.2.4
asyncpg==0.29.0
httpx==0.25.2
aiohttp==3.9.1
anthropic==0.25.0  # Claude API
fastapi==0.104.1
uvicorn==0.24.0
redis==5.0.1
pyyaml==6.0
mem0-ai==0.1.0  # Mem0 SDK
```

## Scripts Overview

| Script | Purpose | Runs | Frequency |
|--------|---------|------|-----------|
| `onboard.sh` | Full setup (bridge, memory, dashboard) | Manually | Once (initial setup) |
| `setup-bridge.sh` | Initialize bridge + Synapse | By onboard.sh | Once |
| `setup-memory.sh` | Initialize memory service | By onboard.sh | Once |
| `run-dashboard.sh` | Start FastAPI dashboard | Manually | On demand |
| `matrix-listener.py` | Chat listener daemon | Background | Always |
| `seed-knowledge.py` | One-off knowledge ingestion | Manually | Ad-hoc |
| `seed-code.py` | Index source code | Manually | Ad-hoc |
| `full-chat-seed.py` | Bulk chat history import | Manually | Once |

## Plugin Skills & Agents

**Skills (Claude Code extensions):**
- `chat-autopilot/` — Main chat interaction, message routing
- `jira-knowledge/` — Jira sprint, issue, linking
- `gitlab-knowledge/` — GitLab MR, pipeline, code session
- `confluence-search/` — Search Confluence docs
- `openkhang-status/` — Check system health, draft queue
- Others: chat-scan, chat-reply, chat-spaces, chat-auth, chat-listen, etc

**Agents (Claude Code multi-step workflows):**
- `bug-investigator` — Investigate urgent bugs, determine fixability
- `chat-categorizer` — Categorize patterns, extract entities
- `sprint-monitor` — Track sprint progress, identify blockers
- `pipeline-fixer` — Auto-fix CI/CD failures

## Large Files (by Token Count)

| File | Tokens | Purpose |
|------|--------|---------|
| plans/reports/researcher-memory-architecture.md | 7,345 | Memory design findings |
| plans/reports/researcher-workflow-patterns.md | 6,830 | Workflow engine design |
| config/style_examples.jsonl | 6,738 | Chat examples for tuning |
| plans/reports/researcher-local-dashboard.md | 4,375 | Dashboard design findings |
| scripts/matrix-listener.py | 3,529 | Chat listener implementation |

## Module Dependency Graph

```
matrix-listener.py
    ↓
    Redis (pub/sub)
    ↓
    ┌─────────────┬──────────────┬──────────────┬──────────────┐
    ↓             ↓              ↓              ↓              ↓
Ingestion     Agent Pipeline  Workflow Engine  Dashboard    Memory Service
(Jira, Git,  (Classify,      (State machine,  (FastAPI,    (Mem0, pgvector,
 Confluence,  Confidence,      Audit log)      HTMX, SSE)   episodic)
 Code)        Prompt, LLM)
    │             │              │              │              │
    └─────────────┴──────────────┴──────────────┴──────────────┘
                          ↓
                    ┌─────────────┐
                    │ Services    │
                    ├─────────────┤
                    │ Postgres    │
                    │ Redis       │
                    │ OpenRouter  │
                    │ Synapse     │
                    └─────────────┘
```

## Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Secrets (MERIDIAN_URL, ANTHROPIC_API_KEY fallback, DB creds) |
| `config/persona.yaml` | Identity, style, never_do rules |
| `config/confidence_thresholds.yaml` | Per-room auto-send thresholds |
| `config/projects.yaml` | Code projects to index (3 repos) |
| `config/style_examples.jsonl` | Chat examples for voice tuning |
| `config/workflows/*.yaml` | State machine definitions |
| `docker-compose.yml` | Infrastructure services (postgres, redis) |

## Development Workflow

1. **Code changes:** Edit in `services/{component}/`
2. **Type check:** Use type hints (mandatory)
3. **Tests:** `pytest services/{component}/tests/ -v`
4. **Run service locally:**
   ```bash
   cd services
   source .venv/bin/activate
   python3 -m uvicorn dashboard.app:app --reload
   ```
5. **Commit:** Follow Conventional Commits format
6. **Deploy:** Docker Compose or systemd service

## Testing

- **Framework:** pytest + pytest-asyncio
- **Coverage:** pytest-cov
- **Location:** `services/{component}/tests/`
- **Run:** `pytest services/ -v` (all tests)

Example: `services/agent/tests/test_classifier.py`, `test_confidence.py`, `test_pipeline.py`

## Monitoring & Debugging

- **Logs:** Python `logging` module; configured in `app.py`
- **Health Endpoint:** `GET /health` returns service status
- **Dashboard:** Real-time activity feed via SSE
- **Database:** `psql -d openkhang -c "SELECT COUNT(*) FROM events;"`
- **Redis:** `redis-cli KEYS "openkhang:*"`, `redis-cli PUBSUB CHANNELS`
