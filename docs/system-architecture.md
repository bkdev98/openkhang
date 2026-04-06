# System Architecture: openkhang Digital Twin

## High-Level Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL SYSTEMS                              │
├──────────────────────────────────────────────────────────────────────┤
│  Google Chat    │    Jira          │  GitLab       │  Confluence    │
│  (Workspace)    │    (Cloud)       │  (Cloud)      │  (Cloud)       │
└────────┬────────┴──────┬───────────┴───────┬───────┴────────┬───────┘
         │               │                   │                │
         │  Google Chat  │  HTTP REST APIs   │  Polling       │
         │  API          │  (30-min cycle)   │  (1h for Conf) │
         │               │                   │                │
┌────────▼──────────────▼───────────────────▼────────────────▼────────┐
│                    BRIDGE LAYER                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  mautrix-googlechat (localhost:8090)                           │ │
│  │  • Translates Google Chat API ↔ Matrix protocol               │ │
│  │  • Maintains room mappings, user profiles                    │ │
│  │  • Runs in: ~/.mautrix-googlechat/docker-compose.yml        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                              ▲                                       │
│                              │ Matrix federation                     │
│                              │                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Synapse Matrix Homeserver (localhost:8008)                   │ │
│  │  • Manages rooms, users, state storage                        │ │
│  │  • Mediates between bridge and local clients                 │ │
│  │  • Database: ~/.mautrix-googlechat/data/homeserver.db        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                              ▲                                       │
│                              │ Sync stream (long-polling)            │
│                              │                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  matrix-listener (scripts/matrix-listener.py)                 │ │
│  │  • Subscribes to sync stream from Synapse                     │ │
│  │  • Publishes message events to Redis pub/sub                 │ │
│  │  • Filters: only rooms Khanh is in                           │ │
│  │  • Runs as daemon: python3 scripts/matrix-listener.py --daemon│ │
│  └────────────────────────────────────────────────────────────────┘ │
└────────┬──────────────────────────────────────────────────────────────┘
         │ (Redis events: "chat.message", "chat.reaction", etc.)
         │
┌────────▼──────────────────────────────────────────────────────────────┐
│                    SERVICE LAYER (Python 3.13)                        │
│                    services/.venv + docker-compose                    │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────────┐    ┌──────────────────┐  ┌─────────────────┐ │
│  │ MEMORY SERVICE   │    │  INGESTION LAYER │  │  AGENT PIPELINE │ │
│  │ (services/memory)│    │(services/ingesti │  │ (services/agent)│ │
│  ├──────────────────┤    │on)               │  ├─────────────────┤ │
│  │ • Mem0 Client    │    ├──────────────────┤  │ • Classifier    │ │
│  │ • pgvector store │    │ • ChatIngestor   │  │ • Confidence    │ │
│  │ • Episodic DB    │    │ • JiraIngestor   │  │ • PromptBuilder │ │
│  │ • Working memory │    │ • GitLabIngestor │  │ • LLMClient     │ │
│  │   (30-min TTL)   │    │ • ConfluenceIng  │  │ • Pipeline      │ │
│  │                  │    │ • CodeIngestor   │  │ • MatrixSender  │ │
│  │ Methods:         │    │ • Chunker        │  │ • DraftQueue    │ │
│  │ • add_memory()   │    │ • Scheduler      │  │                 │ │
│  │ • search()       │    │                  │  │ Methods:        │ │
│  │ • search_entity()│    │ Calls:           │  │ • process_msg() │ │
│  │                  │    │ • REST APIs      │  │ • rank_drafts() │ │
│  │ Config:          │    │ • Local git clone│  │ • send_reply()  │ │
│  │ • vector_dim=1024│    │ • Postgres       │  │                 │ │
│  │ • model=bge-m3   │    │ • pgvector       │  │ Config:         │ │
│  │ • embedding_dim: │    │                  │  │ • persona.yaml  │ │
│  │   bge-m3/ollama  │    │ Config:          │  │ • confidence_*. │ │
│  │                  │    │ • projects.yaml  │  │   yaml          │ │
│  │ Port: Mem0 API   │    │ • API keys (.env)│  │                 │ │
│  │ (local)          │    │                  │  │ Port: Redis     │ │
│  │                  │    │ Schedule:        │  │ consumer        │ │
│  │                  │    │ • 30min polling  │  │                 │ │
│  │                  │    │   (Jira, GitLab)│  │ Redis queue:    │ │
│  │                  │    │ • 1h polling     │  │ • pending_drafts│ │
│  │                  │    │   (Confluence)   │  │ • sent_replies  │ │
│  │                  │    │ • Real-time chat │  │                 │ │
│  └──────────────────┘    └──────────────────┘  └─────────────────┘ │
│                                 ▼                        │           │
│                                 │                        │           │
│  ┌──────────────────────────────┴────────────────────────▼─────────┐ │
│  │  WORKFLOW ENGINE (services/workflow)                           │ │
│  ├────────────────────────────────────────────────────────────────┤ │
│  │ • StateMachine (YAML parser)                                   │ │
│  │ • ActionExecutor (runs actions: send_reply, create_jira, etc) │ │
│  │ • WorkflowEngine (coordinates state + actions)                │ │
│  │ • AuditLog (tracks all actions with tier level)               │ │
│  │                                                                │ │
│  │ Example: chat-to-jira.yaml routes patterns to Jira creation   │ │
│  │ Three-tier autonomy:                                          │ │
│  │  • Tier 1: Auto-execute (no approval needed)                  │ │
│  │  • Tier 2: Guided (ask for confirmation before executing)     │ │
│  │  • Tier 3: Human-only (must be manually approved)             │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                 ▼                                    │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ DASHBOARD (services/dashboard:8000)                            │ │
│  ├────────────────────────────────────────────────────────────────┤ │
│  │ FastAPI app.py + HTMX templates + TailwindCSS                 │ │
│  │                                                                │ │
│  │ Routes:                                                        │ │
│  │ • GET / → home (feed, draft count, health)                   │ │
│  │ • GET /drafts → draft queue (pending/reviewed)                │ │
│  │ • POST /drafts/{id}/approve → approve single draft            │ │
│  │ • POST /drafts/{id}/edit → edit and re-send draft             │ │
│  │ • GET /events (SSE) → real-time activity feed                │ │
│  │ • GET /health → service health (postgres, redis, ollama)      │ │
│  │ • POST /twin-chat → query the agent about memories           │ │
│  │                                                                │ │
│  │ Real-time: Server-Sent Events (SSE) for activity feed updates │ │
│  │ Layout: base.html + partials for modular components          │ │
│  │ Styling: TailwindCSS (static/style.css)                       │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
                         ▲          ▲          ▲
                         │          │          │
         ┌───────────────┘          │          │
         │                          │          │
         │                  ┌───────┴──────────┘
         │                  │
┌────────▼──────┬───────────▼────────┬──────────────────────┐
│   Postgres    │      Redis         │     Ollama           │
│   5433        │      6379          │     11434            │
├───────────────┼────────────────────┼──────────────────────┤
│ • pgvector    │ • Pub/sub (message │ • bge-m3 embeddings │
│ • events      │   routing)         │ • Model: 1024-dim   │
│ • draft_      │ • Session store    │ • Native ARM64 (M2) │
│   replies     │   (TTL 30-min)     │ • Runs native       │
│ • sync_state  │ • Job queues       │ • ~2GB RAM          │
│ • workflow_   │                    │                     │
│   instances   │                    │                     │
│ • audit_log   │                    │                     │
└───────────────┴────────────────────┴──────────────────────┘
```

## Core Components

### 1. Memory Service (`services/memory/`)

**Purpose:** Vector search, episodic event storage, session context

**Key Files:**
- `client.py` — Mem0 wrapper; high-level search/add_memory API
- `episodic.py` — Raw event log; appends immutable records
- `working.py` — In-memory TTL cache for session state
- `config.py` — Load config from .env (API keys, Ollama endpoint)
- `schema.sql` — Postgres schema (extensions, tables, indexes)

**Database Tables:**
- `events` — append-only event log (source, event_type, payload, metadata)
- `openkhang_memories` — Mem0-managed table (auto-created)
- `sync_state` — tracks last successful ingest per source

**Key Methods:**
```python
client = MemoryClient(config)
await client.connect()

# Search semantic memory
results = await client.search("what do we know about transaction history?", top_k=5)

# Add to episodic store
await client.add_memory(
    memory="Discussed filtering improvements",
    hash_type="text",
    source="chat",
    created_at="2025-04-06T14:30:00Z"
)

# Session context
session = client.working_memory.get_session(user_id)
```

**Config (from `.env`):**
- `MEM0_API_KEY` — Mem0 API token
- `POSTGRES_DSN` — Connection string
- `OLLAMA_BASE_URL` — Embedding endpoint
- `VECTOR_DIM` — Default 1024 (bge-m3)

### 2. Ingestion Layer (`services/ingestion/`)

**Purpose:** Fetch data from 4 sources, chunk, embed, store

**Ingestors:**
| Ingestor | Source | Schedule | Chunk Unit | Methods |
|----------|--------|----------|-----------|---------|
| `ChatIngestor` | Google Chat (via matrix-listener) | Real-time | Message/paragraph | ingest_message(), search_history() |
| `JiraIngestor` | Jira Cloud REST API | 30-min poll | Ticket + comments | ingest_issue(), search_issues() |
| `GitLabIngestor` | GitLab REST API | 30-min poll | MR + commits | ingest_mr(), search_mrs() |
| `ConfluenceIngestor` | Confluence REST API | 1-hour poll | Page + sections | ingest_page(), search_docs() |
| `CodeIngestor` | Local git repos (3 projects) | On-demand | Class/function | ingest_repo(), search_code() |

**Shared Components:**
- `base.py` — `BaseIngestor` abstract class, common retry logic
- `chunker.py` — `SemanticChunker` (splits by paragraphs, code blocks, tree-sitter)
- `entity.py` — `Entity` dataclass (name, type, description, metadata)
- `scheduler.py` — `IngestScheduler` orchestrates polling
- `sync_state.py` — tracks `last_synced_at`, prevents duplicates

**Data Flow:**
```
Jira API
  ↓
JiraIngestor.ingest_issue()
  ↓
Chunker.chunk_text()  # Split ticket + comments
  ↓
Memory.add_memory()  # Embed + store in pgvector
  ↓
Episodic.append_event()  # Log raw event
  ↓
sync_state.update()  # Mark as synced
```

**Config (`config/projects.yaml`):**
```yaml
projects:
  momo-app:
    path: ~/Projects/momo-app
    language: kotlin
    include_paths: [...]  # Only specific packages
    extensions: [".kt"]
```

### 3. Agent Pipeline (`services/agent/`)

**Purpose:** Process chat message → generate draft → decide auto/manual review

**Key Files:**
- `pipeline.py` — Main orchestrator; coordinates components
- `classifier.py` — Message classification (work/question/social/humor/greeting)
- `confidence.py` — Confidence scoring + modifiers (room, sender, history)
- `prompt_builder.py` — Constructs system + user prompts with RAG context
- `llm_client.py` — Claude API wrapper (with retry, token counting)
- `draft_queue.py` — Manages pending drafts, approval workflow
- `matrix_sender.py` — Sends approved reply back to Matrix (→ Google Chat)

**Pipeline Stages:**

```
1. Receive message from matrix-listener (Redis)
   ↓
2. Classify message (work/question/social/greeting/humor/fyi)
   ↓
3. Fetch context:
   • Search semantic memory (similar past discussions)
   • Get episodic events (last N days of activity)
   • Get sender's role/history
   ↓
4. Build prompt:
   • System: persona.yaml (identity, style, never_do rules)
   • Context: retrieved memory + code snippets
   • User: classify message + safety instructions
   ↓
5. Call Claude API
   → Generate draft reply + confidence score
   ↓
6. Apply confidence modifiers:
   • room_modifier (DM: 0.9, group: 1.2)
   • sender_modifier (lead: 0.8, normal: 1.0)
   • history_modifier (+0.1 if seen similar before)
   ↓
7. Decide: Auto-send or draft?
   if confidence >= threshold AND not from lead AND room graduated:
     send immediately via MatrixSender
   else:
     queue in draft_replies table for human review
   ↓
8. Log to events table (episodic store)
```

**Confidence Scoring:**
```python
def score_confidence(base_score, room_id, sender_role, history_count):
    room_mod = 0.9 if is_dm(room_id) else 1.2
    sender_mod = 0.8 if sender_role in CAUTIOUS_ROLES else 1.0
    history_mod = 0.1 if history_count > 5 else 0.0
    return base_score * room_mod * sender_mod + history_mod
```

**Config (`config/persona.yaml`):**
```yaml
name: Khanh Bui
role: Senior Mobile Engineer
style:
  formality: casual-professional
  emoji_usage: moderate
  response_length: concise
  humor: occasional
  mix_languages: true  # Vinglish

never_do:
  - "Promise deadlines without evidence"
  - "Claim to have attended unlogged meetings"
  - "Share confidential information"
  - ... (6 more hard constraints)

group_chat_rules:
  auto_reply_only: ["request", "question"]
  ignore_in_group: ["social", "humor", "greeting", "fyi"]
  cautious_titles: ["Manager", "Lead", "Director", "VP"]
```

**Prompts (`services/agent/prompts/`):**
- `outward_system.md` — System prompt for acting as Khanh in chat
- `inward_system.md` — System prompt for assistant mode (drafting tasks, reports)

### 4. Workflow Engine (`services/workflow/`)

**Purpose:** YAML state machines for multi-step automation with audit trail

**Key Files:**
- `state_machine.py` — Parser, state transitions, action dispatch
- `action_executor.py` — Executes actions (send_reply, create_jira, trigger_code_session)
- `workflow_engine.py` — Main orchestrator; manages workflow instances
- `workflow_persistence.py` — Load/save workflow state from Postgres
- `audit_log.py` — Records all actions + approvals

**Workflow Example (`config/workflows/chat-to-jira.yaml`):**
```yaml
name: chat-to-jira
trigger: chat.message
states:
  start:
    type: decision
    condition: message.text contains "create ticket"
    on_true: extract_details
    on_false: end
  
  extract_details:
    type: action
    action: extract_jira_fields
    params: [title, description, assignee]
    next: validate
  
  validate:
    type: decision
    condition: all_required_fields_present
    on_true: create_jira
    on_false: ask_for_clarification
  
  create_jira:
    type: action
    action: create_jira_issue
    tier: 2  # Requires confirmation
    next: confirm_in_chat
  
  confirm_in_chat:
    type: action
    action: send_reply
    message: "Created ticket {ticket_id}"
    tier: 1  # Auto-send
    next: end
```

**Three-Tier Autonomy:**
| Tier | Approval | Example |
|------|----------|---------|
| 1 | None | Send simple reply |
| 2 | Guided (show preview) | Create Jira issue |
| 3 | Human-only | Delete messages, revoke access |

**Audit Trail:**
Each action logged to `audit_log` table:
```sql
INSERT INTO audit_log (workflow_id, action_type, tier, params, result, approved_by, created_at)
VALUES (uuid, 'create_jira', 2, {...}, {...}, 'khanh', now());
```

### 5. Dashboard (`services/dashboard/`)

**Purpose:** Web UI for draft review, service health, twin chat

**Key Files:**
- `app.py` — FastAPI main app, route definitions
- `dashboard_services.py` — High-level service logic (fetch drafts, check health)
- `inbox_relay.py` — Consolidate mentions, assignments, flags from all sources
- `agent_relay.py` — Direct communication with agent (send instruction, get response)
- `health_checker.py` — Probe postgres, redis, ollama, matrix-listener
- `twin_chat.py` — Interface with agent for memory queries
- `templates/` — Jinja2 HTML + HTMX + TailwindCSS

**Routes:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Home (activity feed, draft count, health) |
| GET | `/drafts` | Draft queue (pending, approved, rejected, edited) |
| POST | `/drafts/{id}/approve` | Approve draft, queue for auto-send |
| POST | `/drafts/{id}/reject` | Reject draft, mark as not sent |
| POST | `/drafts/{id}/edit` | Edit text, save modified version |
| GET | `/events` (SSE) | Stream activity feed updates (real-time) |
| POST | `/twin-chat` | Query agent: "Summarize discussion about X" |
| GET | `/health` | Service health: postgres, redis, ollama, matrix-listener |

**Real-Time Updates (SSE):**
```python
@app.get("/events")
async def stream_events(request: Request):
    """Server-Sent Events stream for activity feed"""
    async def event_generator():
        # Subscribe to Redis pub/sub
        pubsub = redis_client.pubsub()
        pubsub.subscribe("openkhang:events")
        
        for message in pubsub.listen():
            event = json.loads(message['data'])
            yield f"data: {json.dumps(event)}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**Health Check:**
```python
async def check_health():
    health = {}
    
    # Postgres
    try:
        async with get_db() as conn:
            await conn.fetchval("SELECT 1")
        health['postgres'] = 'ok'
    except Exception as e:
        health['postgres'] = f'error: {str(e)}'
    
    # Redis
    try:
        redis_client.ping()
        health['redis'] = 'ok'
    except Exception as e:
        health['redis'] = f'error: {str(e)}'
    
    # Ollama
    try:
        response = httpx.get("http://localhost:11434/api/models")
        health['ollama'] = 'ok' if response.status_code == 200 else 'error'
    except:
        health['ollama'] = 'unreachable'
    
    return health
```

## Data Flow: Chat Message → Draft → Approval

```
1. User sends message in Google Chat
   
2. Google Chat sends message via API to mautrix-googlechat bridge
   
3. Bridge translates to Matrix event; forwards to Synapse
   
4. matrix-listener subscribes to Synapse sync stream
   Filter: only if Khanh is in the room
   
5. matrix-listener parses event; publishes to Redis:
   {
     "source": "chat",
     "event_type": "message.new",
     "room_id": "!abc:localhost",
     "sender": "user@example.com",
     "text": "Can you review the transaction history PR?",
     "timestamp": "2025-04-06T14:30:00Z"
   }
   
6. Agent pipeline subscribes to Redis; receives message
   
7. Classify: message.text → "work" (request/question)
   
8. Search memory:
   • "transaction history" → retrieve 5 docs with scores
   • Episodic: last 7 days of transaction history discussions
   
9. Build prompt:
   system: persona.yaml (identity, style, safety rules)
   context: retrieved memory + code snippets
   user: "Message from $sender (role: $role): $text"
   
10. Call Claude API → get response + confidence_base
    Response: "I'll take a look and leave feedback by EOD."
    confidence_base: 0.82
    
11. Apply modifiers:
    • room_modifier: 0.9 (is DM) → 0.82 * 0.9 = 0.738
    • sender_modifier: 1.0 (not lead) → 0.738 * 1.0 = 0.738
    • history_modifier: +0.05 (seen similar 3 times) → 0.738 + 0.05 = 0.788
    final confidence: 0.788
    
12. Decision:
    if 0.788 >= 0.75 (default_threshold):
        if is_dm(room) and not sender_is_lead(sender):
            → Send immediately
        else:
            → Queue as draft
    
13. Send to queue:
    INSERT INTO draft_replies (
        room_id, original_message, draft_text, confidence, evidence, status, created_at
    ) VALUES (...)
    
14. Dashboard SSE sends real-time event:
    {
      "type": "draft_created",
      "id": "uuid",
      "room": "transaction-history-feedback",
      "confidence": 0.788,
      "status": "pending"
    }
    
15. User sees in dashboard draft panel
    
16. User reviews, clicks "Approve"
    
17. Draft status → "approved"
    → Pipeline re-sends to MatrixSender
    
18. MatrixSender calls Matrix Client API:
    PUT /_matrix/client/r0/rooms/{room_id}/send/m.room.message
    {
      "msgtype": "m.text",
      "body": "I'll take a look and leave feedback by EOD."
    }
    
19. Matrix delivers to Synapse → mautrix-googlechat → Google Chat
    
20. Message appears in Google Chat as Khanh's reply
    
21. episodic store appends event:
    {
      "source": "chat",
      "event_type": "message.sent",
      "actor": "system",
      "payload": {...}
    }
```

## Deployment Topology

**Infrastructure:**
- **Postgres** (port 5433) — pgvector extension; episodic store + drafts
- **Redis** (port 6379) — event bus (pub/sub); session store
- **Ollama** (port 11434) — local bge-m3 embeddings (native M2 ARM64)
- **Synapse** (port 8008) — Matrix homeserver
- **mautrix-googlechat** (port 8090) — bridge (separate compose)
- **Dashboard** (port 8000) — FastAPI, HTMX, SSE

**Service Layout:**
```
~/.mautrix-googlechat/          # Synapse + mautrix bridge
  ├── docker-compose.yml
  ├── data/                      # Synapse state DB
  └── ...

./services/                      # Python services
  ├── .venv/                     # Shared virtualenv
  ├── requirements.txt           # All service deps
  ├── memory/                    # Mem0 + pgvector
  ├── ingestion/                 # Ingestors
  ├── agent/                     # Pipeline
  ├── workflow/                  # State machines
  └── dashboard/                 # FastAPI web UI

./docker-compose.yml            # Postgres + Redis + Ollama
```

## Security Boundaries

| Boundary | Type | Controls |
|----------|------|----------|
| Google Chat ↔ Bridge | External API | mautrix-googlechat OAuth token in .env |
| Bridge ↔ Synapse | Internal (localhost) | No auth (local network only) |
| Synapse ↔ matrix-listener | Sync stream | No auth (localhost only) |
| Services ↔ Postgres | Database | Localhost-only; no public exposure |
| Services ↔ Redis | Event bus | Localhost-only; no auth (internal) |
| Services ↔ Ollama | Embedding | Localhost-only; no auth |
| Dashboard ↔ User | Web browser | Future: session token auth |
| Claude API calls | External | API key in .env; sent only context, no raw chat |

## Scalability Considerations

**Current Limits:**
- **Memory:** Single Python process (agent + dashboard share); ~500MB heap
- **Throughput:** ~100 messages/min (limited by Jira/GitLab polling, 30min cycle)
- **Storage:** Postgres ~10GB for 1 year of events (estimate: 100 messages/day)
- **Latency:** 2s message → draft (dominated by Claude API call)

**Future Improvements:**
- Separate services into microservices (memory, ingestion, agent, dashboard)
- Queue worker pool for parallel ingestion
- Webhook integration (real-time Jira/GitLab instead of polling)
- Caching layer (Redis for frequently retrieved contexts)
- Batch embedding (accumulate messages, embed in bulk)
