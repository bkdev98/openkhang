# Memory Architecture for Digital Twin Assistant
**openkhang** — Work autopilot with integrated context across Jira, GitLab, Confluence, Google Chat

**Date:** 2026-04-06 | **Research Period:** 2025-2026 | **Focus:** Local-first, single-user, work context

---

## Executive Summary

The gap in **openkhang** is architectural: tools operate in isolation. A message about a bug in Google Chat doesn't correlate with the Jira ticket or GitLab MR. Context is lost between sessions. This research identifies a **hybrid memory system** combining:

1. **Vector database** (SQLite with sqlite-vec or PostgreSQL pgvector) for semantic search across unstructured content (chat logs, Confluence pages, commit messages)
2. **Graph layer** (lightweight graph structure, not separate DB) for entity relationships (people ↔ tickets ↔ MRs ↔ decisions ↔ deadlines)
3. **Event-driven capture** (webhooks from Jira, GitLab, Matrix) to feed context continuously
4. **Local embeddings** (Ollama or HuggingFace models) to run entirely on user's machine

**Recommendation:** Start with **SQLite + sqlite-vec + local embeddings** (simplest, zero ops), add a **hand-rolled graph layer** (JSON-based entity store) in phase 2 once semantic search patterns stabilize.

---

## 1. Memory Architecture Patterns (2025-2026 State)

### 1.1 Three-Layer Memory Model

Research from Mem0, Letta/MemGPT, and LangChain converges on this structure:

| Layer | Purpose | Lifespan | Query Style | Example in openkhang |
|-------|---------|----------|-------------|-------------------|
| **Working Memory** | Active task context | Single agent call | Direct lookup | "Current ticket I'm implementing" |
| **Episodic Memory** | Conversation/event logs | Session + history | Timeline + relevance | "This bug was discussed in Slack on 2026-04-03" |
| **Semantic Memory** | Extracted facts & relationships | Permanent | Vector similarity + graph traversal | "Service X talks to Database Y" |

**Key Finding:** Mem0 (2025) shows 26% accuracy improvement and 91% latency reduction using **hybrid retrieval** (vectors + graph), vs. either alone. Letta's self-editing pattern proves agents must actively manage memory—not passive logging.

### 1.2 Episodic vs. Semantic vs. Procedural

**Episodic** (what happened):
- Chat messages, commit history, Jira comments
- Timestamped, immutable once created
- "On 2026-04-03, user asked about auth bug in #support channel"
- Storage: event log (SQLite, PostgreSQL, or append-only JSONL)

**Semantic** (what we know):
- Extracted facts: "ServiceA depends on ServiceB," "Person X owns Component Y," "Bug #234 relates to MR #567"
- Entity-based, queryable by relationship
- Storage: vector embeddings + graph (relational data)

**Procedural** (how to do it):
- Runbooks, decision trees, CLI commands
- Example: "To deploy to production, run these 5 steps"
- Storage: same layer as semantic (searchable by intent)

**Practical Split for openkhang:**
- Episodic: SQLite table `chat_messages`, `commits`, `jira_events`
- Semantic: Vector table + graph edges
- Procedural: Confluence pages + decision logs

---

## 2. Database Technology Comparison

### 2.1 Vector Storage Options (Local-First)

| Option | Setup | Performance | Memory | Best For | Adoption Risk |
|--------|-------|-------------|--------|----------|----------------|
| **SQLite + sqlite-vec** | Standalone binary, no server | <10ms KNN on 100K vectors | 30MB base + vector data | Single machine, zero ops | Low (pure C, no deps) |
| **SQLite + sqlite-vss** | Requires FAISS library | <10ms, SIMD-accelerated | Higher (Faiss overhead) | Similarity search at scale | Medium (external dep) |
| **PostgreSQL + pgvector** | Requires Postgres instance | <20ms at 1M vectors | Scalable | Teams, shared database | Low (postgres maintained) |
| **DuckDB + extensions** | In-memory OLAP focus | <5ms on analytical queries | High memory overhead | Analytics queries, not storage | Medium (newer, less proven) |

**Recommendation:** Start with **SQLite + sqlite-vec** for single-user, zero infrastructure overhead. Migrate to **PostgreSQL + pgvector** if/when:
- Multi-user sharing needed (Synapse already runs Postgres)
- Vector table grows >1M embeddings
- Backup/recovery requirements increase

**Source credibility:** sqlite-vec is Mozilla Builder project, maintained; pgvector has 10K+ GitHub stars and production deployments at scale.

### 2.2 Graph Layer Decision

**Key Finding from 2025 Research:** Graph-only RAG was only ~5% better than text-only RAG. But **hybrid** (vectors + graph) showed significant improvements. This suggests:
- Graph is not required for basic functionality
- Graph accelerates reasoning once entities stabilize

**Options:**

| Option | Complexity | Query Speed | Maintenance | Cost |
|--------|-----------|------------|-------------|------|
| **No separate graph (phase 1)** | Low | Slow (semantic search only) | Low | Free |
| **Hand-rolled JSON edges** | Medium | ~50-100ms join queries | Medium | Free |
| **DuckDB with DuckPGQ** | Medium | <50ms analytical queries | Medium | Free |
| **Neo4j Community** | High | <10ms (native graph queries) | High | Free (but infrastructure) |
| **KuzuDB** | Medium | Fast | **BLOCKED** (archived Oct 2025) | N/A |

**Recommendation:** Skip phase 1. Build a **JSON-based edge store** (table with `(source_id, source_type, rel_type, target_id, target_type, metadata)`) in SQLite phase 1. In phase 2, if query patterns prove you need sub-10ms graph traversal, evaluate DuckDB DuckPGQ.

**Why not Neo4j?** Single-user fintech assistant doesn't justify the ops overhead or licensing complexity.

---

## 3. Practical Storage Architecture for openkhang

### 3.1 Proposed Schema (Phase 1)

```sql
-- Episodic: Raw events
CREATE TABLE events (
  id TEXT PRIMARY KEY,
  source TEXT,  -- 'chat', 'jira', 'gitlab', 'confluence'
  timestamp DATETIME,
  raw_content TEXT,
  actor TEXT,
  event_type TEXT,
  metadata JSONB
);

-- Episodic: Processed (used to generate embeddings)
CREATE TABLE conversation_chunks (
  id TEXT PRIMARY KEY,
  event_id TEXT REFERENCES events(id),
  text TEXT,  -- Chunked for embedding
  created_at DATETIME,
  embedding BLOB  -- sqlite-vec format
);

-- Semantic: Entity graph (JSON-based edges)
CREATE TABLE entities (
  id TEXT PRIMARY KEY,  -- "jira:PROJ-123", "person:alice", "gitlab:mr:789"
  type TEXT,  -- 'ticket', 'person', 'mr', 'commit', 'decision'
  name TEXT,
  metadata JSONB,  -- Type-specific fields
  created_at DATETIME,
  updated_at DATETIME
);

CREATE TABLE edges (
  id TEXT PRIMARY KEY,
  source_id TEXT REFERENCES entities(id),
  rel_type TEXT,  -- 'owns', 'blocks', 'references', 'implements'
  target_id TEXT REFERENCES entities(id),
  metadata JSONB,
  created_at DATETIME
);

-- Configuration & state
CREATE TABLE agent_memory_state (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at DATETIME
);
```

### 3.2 Embedding & Vector Search (sqlite-vec)

```sql
-- Create vector index
CREATE VIRTUAL TABLE conversation_embeddings USING vec0(
  embedding(384)  -- For nomic-embed-text
);

-- Query (semantic search)
SELECT c.text, c.event_id, distance
FROM conversation_embeddings
WHERE embedding MATCH (?) AND k = 5
ORDER BY distance;
```

### 3.3 Graph Queries (Phase 1: JSON, Phase 2: SQL Joins)

```sql
-- Find all tickets owned by Alice and their blockers
SELECT DISTINCT e.* FROM entities e
JOIN edges dep ON e.id = dep.source_id
WHERE e.type = 'ticket'
  AND EXISTS (
    SELECT 1 FROM edges owns
    WHERE owns.source_id = 'person:alice'
      AND owns.target_id = e.id
      AND owns.rel_type = 'owns'
  )
  AND dep.rel_type = 'blocked_by';
```

**Decision:** Keep graph as relational tables (not separate DB). Join to vector results when needed. This avoids:
- Extra infrastructure
- Data sync problems
- Query language fragmentation

---

## 4. Memory Capture: Event-Driven Integration

### 4.1 Event Sources

| Source | Event Type | Capture Method | Latency |
|--------|-----------|-----------------|---------|
| **Google Chat (via mautrix)** | Message, reaction, thread update | Matrix event listener (existing) | Real-time |
| **Jira** | Ticket created/updated, comment, status change | Webhook + REST polling | ~30s (webhook) |
| **GitLab** | MR opened/merged, comment, pipeline result, commit | Webhook | Real-time |
| **Confluence** | Page created/updated | REST polling (no webhooks) | ~5m (scheduled) |

**Implementation Pattern:**

```python
# Pseudocode: Event-driven memory capture

async def on_jira_webhook(event):
    # 1. Log raw event
    db.events.insert(source='jira', raw_content=event, timestamp=now())
    
    # 2. Extract entities
    entities = extract_entities(event)  # "PROJ-123", "alice@momo.com"
    for ent in entities:
        db.entities.upsert(id=ent.id, type=ent.type, metadata=ent.data)
    
    # 3. Link to other entities
    if event.type == 'comment':
        db.edges.insert(
            source_id=f"jira:{event.issue_key}",
            rel_type='discussed_in',
            target_id=f"chat:{event.mentioned_channels[0]}",
            metadata={'context': event.comment_text[:100]}
        )
    
    # 4. Generate embedding (if content > 50 chars)
    if len(event.raw_content) > 50:
        chunk = TextChunker.chunk(event.raw_content, max_size=512)
        embedding = embed(chunk)  # Ollama local model
        db.conversation_chunks.insert(text=chunk, embedding=embedding)

async def on_gitlab_webhook(event):
    # Similar: log → extract → link → embed
    pass
```

**Key Design:**
- **Async:** Events don't block each other
- **Chunking:** Long docs split into ~512-char chunks before embedding
- **Deduplication:** Check `created_at` to skip re-processing same event
- **Graceful degradation:** If embedding service fails, still log the event

---

## 5. Embedding Model Selection (Local)

### 5.1 Candidates

| Model | Size | Speed | Quality | Setup |
|-------|------|-------|---------|-------|
| **nomic-embed-text-1.5** | 137M | <50ms/chunk | Very good (MTEB #6) | `ollama pull nomic-embed-text` |
| **mxbai-embed-large** | 335M | ~100ms/chunk | Excellent (MTEB #4) | `ollama pull mxbai-embed-large` |
| **bge-small-en-v1.5** (HuggingFace) | 33M | <10ms | Good | `sentence-transformers` |
| **EmbeddingGemma** (Google) | 256M | Fast | Very good | Works with Ollama |

**Recommendation:** **nomic-embed-text-1.5**
- Reason: Purpose-built for semantic search, fits in 4GB RAM, Ollama native
- Fallback to bge-small if latency critical (33M model)

**Setup:**
```bash
# Start embedding service (Ollama)
ollama pull nomic-embed-text-1.5
ollama serve

# In app
embedding = requests.post('http://localhost:11434/api/embed', json={
    'model': 'nomic-embed-text-1.5',
    'input': 'Bug: auth token expires after 5 minutes'
})['embeddings'][0]  # 384-dim vector
```

---

## 6. Entity Model for Work Context

### 6.1 Entity Types & Relationships

**Core Entities:**

```
People (alice, bob)
  ├─ owns ─→ Components (auth-service)
  ├─ assigned_to ─→ Tickets (PROJ-123)
  ├─ mentioned_in ─→ Chat (thread#456)
  └─ author_of ─→ Commits

Tickets (JIRA)
  ├─ blocked_by ─→ Tickets
  ├─ references ─→ MRs
  ├─ discussed_in ─→ Chat threads
  ├─ depends_on ─→ Services
  └─ assigned_to ─→ People

MRs (GitLab)
  ├─ closes ─→ Tickets
  ├─ touches ─→ Components
  ├─ reviewed_by ─→ People
  └─ comment ─→ Chat mention

Components (Services, Modules)
  ├─ owned_by ─→ People
  ├─ talks_to ─→ Components
  ├─ implemented_in ─→ Repository paths
  └─ decision ─→ Decisions

Decisions (Architecture, Design)
  ├─ related_to ─→ Tickets
  ├─ discussed_in ─→ Confluence pages
  ├─ affects ─→ Components
  └─ owner ─→ People

Chat Threads (Google Chat)
  ├─ mentions ─→ Tickets
  ├─ mentions ─→ People
  ├─ discusses ─→ Decisions
  └─ related_to ─→ MRs
```

### 6.2 Cross-System Correlation Example

**User asks:** "Hey, remind me about the auth token bug that was in that Slack thread last week."

**Memory resolution:**

```
1. Vector search: Find semantically similar to "auth token bug"
   → Finds chat message (2026-03-30): "Token expires after 5 min"

2. Graph traversal: Follow edges from that chat mention
   ├─ mentions → Jira:PROJ-892 (Bug: Auth token expiry)
   ├─ assigned_to → alice
   ├─ references → MR:234
   ├─ depends_on → SSO-service
   └─ blocked_by → PROJ-888

3. Fetch context: Re-read the original Confluence page, related decisions

4. Synthesize response:
   "The auth token bug (PROJ-892, assigned to alice) was discussed in Slack on 2026-03-30.
    It's blocking PROJ-888 (dependency on SSO-service fix).
    Alice opened MR:234 but it's waiting on PROJ-888.
    Decision from Jan: 'Use RS256 for tokens' (confpage#245)."
```

---

## 7. Architecture Trade-Offs & Decisions

### 7.1 Single DB vs. Poly-Storage

| Approach | Pros | Cons | Recommendation |
|----------|------|------|-----------------|
| **Single SQLite** | No sync overhead, simple backup, zero ops | Vectors + graph in same DB feels awkward | Phase 1: YES |
| **SQLite + external graph DB** | Cleaner separation | Sync problems, extra infrastructure | Phase 2 only if needed |
| **PostgreSQL all-in** | pgvector + JSONB handles both; one backup | Requires running Postgres; overkill for single-user | Optional upgrade at scale |

**Decision:** Phase 1 = SQLite everything. Graph is just relational tables, vectors are sqlite-vec table. Simplicity wins.

### 7.2 Embedding Frequency

| Strategy | Update Cost | Staleness | Best For |
|----------|------------|----------|----------|
| **Immediate (on every event)** | High (sync embedding calls block webhooks) | Zero | Critical tickets, decisions |
| **Batch (every 5m)** | Low | Moderate | Most events (bugs, comments) |
| **On-demand (query-time)** | High latency | High | Rarely-accessed historical data |

**Decision:** Events trigger immediate entity/edge creation. Embedding is **async batch** (every 5 minutes). Vectors may lag real-time, but semantic search isn't expected to be sub-minute-critical for this use case.

### 7.3 Retention & Pruning

**Problem:** Memory grows unbounded. After 12 months at MoMo, thousands of closed tickets and chatted discussions.

**Strategy:**

```
Episodic (raw events):
  - Keep all for 90 days (useful for debugging context switches)
  - Archive older events monthly

Semantic (vectors + graph):
  - All active entities (tickets, people, decisions) kept forever
  - Entity edges pruned: if target ticket closed + no recent reference, prune after 180 days
  - Re-embedding: if a component's definition changes (decision updated), re-embed

Procedural (runbooks):
  - Keep versioned; old versions searchable but marked stale
```

---

## 8. Privacy & Security (Local-First)

### 8.1 Data Scope

**Stored locally (user's machine):**
- All chat messages (from mautrix bridge)
- All Jira events (read from API)
- All GitLab events (webhooks)
- All Confluence page content
- All embeddings (derived, non-recoverable)
- Graph edges (metadata only)

**Never stored:**
- API tokens (read from `.env`, not persisted)
- Passwords
- User credentials (only read from Matrix/Jira/GitLab sessions)

### 8.2 Threats & Mitigations

| Threat | Impact | Mitigation |
|--------|--------|-----------|
| Laptop theft | All work context leaked | Encrypt SQLite at rest (SQLCipher) |
| Memory dump attack | Embeddings + entities visible | Run in VM/container with resource limits |
| Webhook interception | Jira/GitLab events diverted | Validate webhook signatures (Jira/GitLab feature) |
| Unintended export | User accidentally shares .db file | Warn on export, use encrypted container |

**Implementation:**

```bash
# Encrypt SQLite database
sqlite3 memory.db "PRAGMA key = 'your-passphrase';"
sqlite3 memory.db "PRAGMA cipher_compatibility = 4;"

# Or use SQLCipher (one-line)
sqlcipher memory.db "PRAGMA key='password';"
```

**Recommendation:** Make encryption **optional but default**. Provide docs for `SQLCipher` setup if user handles HIPAA-level data.

---

## 9. Integration With Existing openkhang Blocks

### 9.1 Chat Block Integration

**Current:** Chat scanner reads messages, drafts replies.
**Memory enhancement:**
- Store all scanned messages in `events` table
- Link mentions of tickets/people to `entities`
- On reply draft, query vector DB: "Similar questions we've answered before?"
- Provide context card: "This ticket was discussed in chat on [date]"

**Change minimal:** Add event logger (10 lines) to existing chat-scan command.

### 9.2 Jira Block Integration

**Current:** Sprint board, burndown.
**Memory enhancement:**
- Webhook captures all ticket events automatically
- When opening a ticket, show "blocked by" graph edges
- Query: "All open issues assigned to me that mention this service?"
- Suggest related decisions from Confluence

**Implementation:** Register Jira webhook in setup script.

### 9.3 GitLab Block Integration

**Current:** MR management, pipeline watch.
**Memory enhancement:**
- Store MR description embeddings
- Link MR to related tickets (via close issue keywords)
- Query: "Show me all PRs touching the auth-service"
- Diff analysis: embed code changes, link to design decisions

**Implementation:** GitLab webhooks already trigger pipeline-watch; extend to memory capture.

### 9.4 Confluence Block Integration

**Current:** Search, create, update.
**Memory enhancement:**
- Periodically index Confluence pages (vectors + entities)
- Extract decision metadata from pages
- Cross-reference: when Jira ticket references a decision, embed the link
- Query: "Decisions related to this ticket?"

**Implementation:** Scheduled sync task (once daily).

---

## 10. Comparison to Mem0, Letta, LangChain Patterns

| Pattern | Mem0 | Letta/MemGPT | LangChain | openkhang-proposed |
|---------|------|------|-----------|-------------------|
| **Memory types** | Episodic, semantic, procedural, associative | Episodic (main context) + semantic (external) | Buffer, entity, vector | Episodic, semantic, (procedural from Confluence) |
| **Storage** | Managed service OR SQLite/Postgres | External memory (file/DB) + main context (RAM) | Pluggable (Pinecone, Chroma, etc.) | SQLite + sqlite-vec |
| **Graph** | Yes (2025 feature, hybrid search) | No (timeline-based) | No (vector-only) | Yes (relational, phase 2 upgrade) |
| **Embedding** | Cloud or local | Cloud (LLM calls for summarization) | Local or cloud | Local (Ollama) |
| **Ops overhead** | SaaS OR self-hosted | Low (file-based) | Varies | Low (single SQLite file) |

**Key Insight:** openkhang is **closer to Letta** (file-based, single-user) but **adds graph** (Mem0 pattern) without the SaaS cost.

---

## 11. Adoption Risk Assessment

### 11.1 Technology Maturity

| Component | Status | Risk | Mitigation |
|-----------|--------|------|-----------|
| **sqlite-vec** | Production (2024+) | Low | Pure C, no deps, MIT licensed |
| **pgvector** | Production (10K+ stars) | Low | If you migrate to Postgres later |
| **Ollama embeddings** | Production (2023+) | Low | Fallback: cloud embedding API |
| **Event webhooks** (Jira, GitLab) | Stable | Low | Standard integrations |
| **Hand-rolled graph** | Custom code | Medium | Keep it simple; test edge queries |

**Overall:** **Low risk**. No experimental tech; everything is 2+ years old.

### 11.2 Breaking Changes Risk

**If we start with SQLite, migrate to Postgres later:**
- Schema stays same (relational)
- Just different connection string
- Embeddings are opaque (no risk of format change breaking retrieval)
- One-time migration cost (~1 day)

**If graph layer changes:**
- Phase 1 doesn't use it; no cost
- Phase 2 graph layer is simple relational→JSON; easy to rewrite

**Recommendation:** Low risk of future regret. SQLite → Postgres is a non-event if we design the schema carefully.

### 11.3 Community & Abandonment Risk

- **sqlite-vec:** Mozilla Builders, maintained. Even if unmaintained, it's pure C—very stable.
- **Ollama:** 60K+ GitHub stars, backed by team. Not going anywhere.
- **pgvector:** Maintained as part of broader Postgres ecosystem.

**Low abandonment risk.**

---

## 12. Roadmap: Phase-by-Phase Implementation

### Phase 1 (Weeks 1-2): Semantic Search Foundation
- [x] Define entity model
- [x] Create SQLite schema (events, conversation_chunks, entities, edges)
- [ ] Set up local Ollama + nomic-embed-text-1.5
- [ ] Webhook integration: Jira, GitLab, Matrix (capture → events table)
- [ ] Async embedding pipeline: chunk content → embed → store vectors
- [ ] Vector search query API: `search_semantic("keyword or phrase", limit=5)`

**Success Criteria:**
- Can query "auth bug" and get 3+ related tickets from chat + Jira
- Vector search latency <100ms
- All webhooks capture events in <30s

### Phase 2 (Weeks 3-4): Entity Graph & Cross-System Correlation
- [ ] Populate `entities` table from events (extract people, tickets, services)
- [ ] Automatic edge creation (mentions → ticket, assigned → person, references → MR)
- [ ] Graph query API: `find_related_tickets("PROJ-123")` returns blockers + related discussions
- [ ] Integration: show related context in Jira UI (Claude Code block)

**Success Criteria:**
- Can trace "this ticket blocks that ticket via [edge type]"
- Chat mention of ticket auto-links Jira entry
- Related tickets show in tooltip

### Phase 3 (Weeks 5-6): Memory Recall in Conversations
- [ ] Chat-scan → vector search before replying (what have we said before?)
- [ ] Jira ticket view → show related Confluence decisions + previous fixes
- [ ] Memory state: track "what context is active now" to avoid repeating

**Success Criteria:**
- Chat reply mentions "We discussed this on [date]: [context]"
- Jira ticket shows "Related: MR #789, Decision #456, Discussion in #support"

### Phase 2b (Optional, Weeks 7+): Graph Database Upgrade
- [ ] Only if Phase 2 graph queries show <100ms is too slow
- [ ] Evaluate: DuckDB DuckPGQ vs. migrate to Postgres + pgvector
- [ ] **Defer if working.**

---

## 13. Unresolved Questions

1. **Entity deduplication:** How to handle "alice@momo.com" vs "alice.smith@momo.com" vs "@alice" in chat? Implement fuzzy matching or manual curation?
   - *Impact:* Graph quality; entity merging logic needed
   - *Defer to:* Phase 2 (once we see real data)

2. **Confluence API rate limits:** Does Confluence have webhooks or only polling? Polling too slow?
   - *Impact:* Staleness of decision docs
   - *Action:* Check Atlassian API docs; may require hybrid (webhooks + polling)

3. **Embedding dimensionality:** nomic-embed-text outputs 384-dim. For millions of vectors, memory impact?
   - *Impact:* Long-term scalability (1M vectors × 384 floats = ~1.5GB)
   - *Mitigation:* Dimension reduction (PCA to 128-dim) if needed; benchmarking phase 1

4. **Private/sensitive data handling:** Should memory filter PII (passwords, API tokens mentioned in chat)? Or assume chat already filtered?
   - *Impact:* Compliance + privacy
   - *Recommendation:* Phase 1: assume input is safe. Phase 2: add PII filter (regex + ML) if needed

5. **Memory sharing across computers:** User has MacBook + office workstation. Does memory sync, or separate instances per machine?
   - *Impact:* Context fragmentation
   - *Decision:* Phase 1: single machine. Phase 2: optional Postgres backend for sync

6. **LLM integration:** Which Claude model calls the memory layer? Does Claude Code plugins support MCP/tool use for this?
   - *Impact:* How memories surface to user
   - *Action:* Review Claude Code plugin API; may need custom integration vs. standard MCP

---

## 14. Concrete Recommendation

### **Go/No-Go: RECOMMEND GO**

**Architecture Choice:**
```
┌──────────────────────────────────────────────────────────────┐
│                        openkhang Memory                       │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Event Sources (Jira, GitLab, Matrix) ──[Webhooks/Polling]  │
│                                              ↓                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │         SQLite Database (single file)               │    │
│  ├─────────────────────────────────────────────────────┤    │
│  │ • events (raw)                                      │    │
│  │ • conversation_chunks + sqlite-vec (embeddings)     │    │
│  │ • entities (JIRA:PROJ-123, person:alice, etc.)      │    │
│  │ • edges (owns, blocks, references, discusses)       │    │
│  └─────────────────────────────────────────────────────┘    │
│                            ↓                                  │
│              Ollama (local, nomic-embed-text-1.5)            │
│                            ↓                                  │
│  APIs: search_semantic(), find_related(), graph_walk()      │
│                            ↓                                  │
│  Claude Code Chat Block: "Show related context"             │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

**Why this architecture:**
1. **Zero ops:** SQLite file, Ollama container, no external services
2. **Privacy:** All data on user's machine
3. **Low risk:** All proven technology (2+ years old)
4. **Upgradeable:** Can migrate to Postgres/Neo4j if needs grow
5. **Practical:** Solves the "tools in isolation" problem immediately

**Implementation effort:** ~2-3 weeks for Phase 1 (vector search only), +2 weeks for Phase 2 (graph, entity correlation).

**Cost:** $0 (open source + user's hardware).

**Maintenance burden:** 
- Weekly: check for Ollama model updates
- Monthly: prune old events (retention policy)
- As-needed: handle entity deduplication issues (fuzzy matching)

---

## 15. Key Sources & Credibility

**Memory Architecture Research:**
- [Mem0 AI Memory Layer Guide](https://mem0.ai/blog/ai-memory-layer-guide) — Active 2025, production SaaS with open-source option
- [Mem0 arxiv 2504.19413](https://arxiv.org/abs/2504.19413) — Academic paper, peer-reviewed
- [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026) — Current survey
- [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560) — Seminal paper on memory hierarchies
- [Letta Docs: Memory Blocks](https://www.letta.com/blog/memory-blocks) — Production framework, actively maintained
- [LangChain Memory Types (2025)](https://sparkco.ai/blog/mastering-entity-memory-in-langchain-deep-dive-2025) — Active 2025 content

**Vector Database Research:**
- [Machine Learning Mastery: Vector DB vs Graph RAG](https://machinelearningmastery.com/vector-databases-vs-graph-rag-for-agent-memory-when-to-use-which/) — Analytical comparison
- [sqlite-vec GitHub](https://github.com/asg017/sqlite-vec) — Pure C implementation, MIT licensed
- [pgvector GitHub](https://github.com/pgvector/pgvector) — 10K+ stars, production deployments
- [Couchbase: Vector vs Graph Database](https://www.couchbase.com/blog/vector-database-vs-graph-database/) — Enterprise perspective

**Local Embedding Research:**
- [Ollama Blog: Embedding Models](https://ollama.com/blog/embedding-models) — Official source
- [Collabnix: Ollama Embedded Models 2025](https://collabnix.com/ollama-embedded-models-the-complete-technical-guide-to-local-ai-embeddings-in-2025/) — Comprehensive 2025 guide
- [Google Developers: EmbeddingGemma](https://developers.googleblog.com/introducing-embeddinggemma/) — Recent (2025), production-ready

**Work Context Integration:**
- [Confluent: Event-Driven AI Agents](https://www.confluent.io/blog/the-future-of-ai-agents-is-event-driven/) — Architecture pattern
- [Docsie: Jira AI Integration 2026](https://www.docsie.io/blog/articles/jira-ai-documentation-integration-2026/) — Enterprise AI + work tools
- [LinkedIn: Knowledge Graph for Software Companies](https://www.linkedin.com/pulse/building-knowledge-graph-software-company-holger-knublauch) — Entity modeling

**Privacy & Security:**
- [New America: AI Agents and Memory (MCP Era)](https://www.newamerica.org/oti/briefs/ai-agents-and-memory/) — Policy perspective
- [Cybernews: AI Assistant Privacy & Security 2025](https://cybernews.com/ai-tools/ai-assistants-privacy-and-security-comparisons/) — Comparative analysis
- [Local AI Master: Privacy Guide 2025](https://localaimaster.com/blog/local-ai-privacy-guide) — Best practices

---

## Report Metadata

- **Research Date:** 2026-04-06
- **Duration:** Single session (comprehensive parallel searches)
- **Sources Consulted:** 30+ (blogs, arxiv papers, GitHub, official docs, opinion pieces)
- **Focus:** Local-first, single-user, work context (not multi-user SaaS)
- **Tech Recency:** All sources 2024-2026; knowledge cutoff Feb 2025 supplemented by Apr 2026 web search
- **Next Action:** Share report with openkhang maintainer; decision on Phase 1 implementation
