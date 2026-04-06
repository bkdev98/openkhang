---
phase: 2
title: Knowledge Ingestion Pipeline
status: Pending
priority: P1
effort: 8h
depends_on: [1]
---

# Phase 2: Knowledge Ingestion Pipeline

## Context Links

- Phase 1: [Memory Foundation](phase-01-memory-foundation.md) — must be complete
- Existing skills: `skills/jira-knowledge/`, `skills/gitlab-knowledge/`, `skills/confluence-knowledge/`
- Existing CLIs: `jira` (jira-cli), `glab` (GitLab CLI), `atlassian-cli` (Confluence)
- Chat data: `.claude/gchat-inbox.jsonl`

## Overview

Build pipelines to ingest knowledge from all four data sources (Google Chat, Jira, GitLab, Confluence) into the memory layer. Chunking, embedding, metadata tagging, and scheduled sync.

## Key Insights

- GitLab repos: chunk by function/class using AST parsing, not naive line splits
- Confluence: chunk by section (h1/h2 boundaries), preserve page hierarchy
- Jira: structured records — embed title+description, link to parent epic and sprint
- Chat: chunk by thread (all messages in a thread = one document), tag participants
- bge-m3 supports up to 8192 tokens — generous chunk sizes possible
- Entity correlation is critical: same person appears in Jira assignee, GitLab author, Chat sender

## Requirements

### Functional
- F1: Ingest Google Chat history from gchat-inbox.jsonl + ongoing from matrix-listener
- F2: Ingest Jira tickets (current sprint + recent backlog) via jira-cli
- F3: Ingest GitLab MRs, commits, pipeline results via glab
- F4: Ingest Confluence pages (specified spaces) via atlassian-cli
- F5: Entity extraction: people, tickets, MRs, pages → graph relationships
- F6: Scheduled re-sync (configurable interval per source)
- F7: Incremental sync — only new/changed items since last run

### Non-Functional
- NF1: Full initial sync completes in <10 minutes
- NF2: Incremental sync completes in <30 seconds
- NF3: Chunking preserves semantic coherence (no mid-sentence splits)

## Architecture

```
┌────────────────────────────────────────────────────┐
│              Ingestion Service (Python)              │
│                                                      │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐│
│  │  Chat    │ │  Jira   │ │  GitLab  │ │Confluence││
│  │ Ingestor │ │Ingestor │ │ Ingestor │ │ Ingestor ││
│  └────┬─────┘ └────┬────┘ └────┬─────┘ └────┬─────┘│
│       │            │           │             │      │
│       └────────────┴───────┬───┴─────────────┘      │
│                            ▼                         │
│                    Chunker + Embedder                │
│                            │                         │
│                            ▼                         │
│                    Entity Extractor                   │
│                            │                         │
│                            ▼                         │
│                    Memory Client (Phase 1)            │
└────────────────────────────────────────────────────┘
```

### Data Flow per Source

**Chat**: gchat-inbox.jsonl → group by thread_event_id → chunk per thread → embed → store with participants metadata
**Jira**: `jira issue list --json` → per ticket: title + description + comments → embed → store with assignee/sprint/epic metadata
**GitLab**: `glab mr list --json` + `glab api` → per MR: title + description + diff summary → embed → link to Jira ticket if ref found
**Confluence**: `atlassian-cli confluence page get` → per page: split by h2 sections → embed → preserve space/parent hierarchy

## Related Code Files

### Create
- `services/ingestion/__init__.py`
- `services/ingestion/base.py` — Abstract ingestor interface
- `services/ingestion/chat.py` — Chat thread ingestor
- `services/ingestion/jira.py` — Jira ticket ingestor
- `services/ingestion/gitlab.py` — GitLab MR/commit ingestor
- `services/ingestion/confluence.py` — Confluence page ingestor
- `services/ingestion/chunker.py` — Text chunking strategies (by-section, by-function, by-thread)
- `services/ingestion/entity.py` — Entity extraction + graph relationship creation
- `services/ingestion/scheduler.py` — Cron-like scheduler for periodic sync
- `services/ingestion/sync_state.py` — Track last-synced timestamps per source

### Modify
- `scripts/matrix-listener.py` — Add Redis pub/sub: publish new messages to event bus (in addition to JSONL)
- `docker-compose.yml` — Add ingestion service

### No Deletes

## Implementation Steps

1. **Create Abstract Ingestor Interface**
   ```python
   class BaseIngestor(ABC):
       @abstractmethod
       async def fetch_new(self, since: datetime) -> list[Document]
       @abstractmethod
       def chunk(self, doc: Document) -> list[Chunk]
       def ingest(self, since: datetime) -> IngestResult:
           docs = self.fetch_new(since)
           for doc in docs:
               chunks = self.chunk(doc)
               for chunk in chunks:
                   embedding = embed(chunk.text)
                   memory_client.add(chunk.text, chunk.metadata, agent_id="system")
               entity_extractor.process(doc)
   ```

2. **Chat Ingestor**
   - Read gchat-inbox.jsonl (existing) + subscribe to Redis channel (new messages from listener)
   - Group messages by `thread_event_id` (or `room_id` if no thread)
   - Chunk: entire thread as one document (threads are typically <50 messages)
   - Metadata: `{source: "gchat", room_name, participants: [], thread_id, timestamp_range}`
   - Entity extraction: participant names → person entities, room names → space entities

3. **Jira Ingestor**
   - Use `jira issue list` with JQL for current sprint + recently updated
   - Chunk: `{title} | {description} | {comments concatenated}` per ticket
   - Metadata: `{source: "jira", key, status, assignee, sprint, epic, priority, labels}`
   - Entity extraction: assignee → person, epic → project, linked issues → relationships

4. **GitLab Ingestor**
   - Use `glab mr list --json` for MRs, `glab api` for commit details
   - Chunk: MR title + description + diff stat summary (not full diff — too large)
   - Metadata: `{source: "gitlab", mr_iid, branch, author, pipeline_status, jira_key}`
   - Cross-reference: extract Jira ticket IDs from branch names and MR descriptions

5. **Confluence Ingestor**
   - Use `atlassian-cli confluence page list` for space, then fetch each page
   - Chunk: split by h2 headers; each section = one chunk with page context
   - Metadata: `{source: "confluence", page_id, space_key, title, section_header, parent_page}`
   - Preserve hierarchy: page → parent page → space relationships in graph

6. **Entity Extraction**
   - Simple regex + heuristic approach (no NER model needed):
     - Jira keys: `/[A-Z]+-\d+/`
     - GitLab MR refs: `/!\d+/`
     - Email/user handles from metadata
     - Confluence page titles from cross-links
   - Create graph edges: `person → works_on → ticket`, `ticket → has_mr → MR`, `MR → documented_in → page`

7. **Modify matrix-listener.py**
   - After `append_to_inbox()`, also publish to Redis channel `openkhang:events`
   - Format: `{type: "chat_message", payload: msg_dict}`
   - Non-breaking change: if Redis unavailable, log warning and continue (JSONL still works)

8. **Scheduler**
   - Simple loop with configurable intervals per source
   - Default: Chat=realtime (event-driven), Jira=5min, GitLab=5min, Confluence=1hr
   - Track `last_synced_at` per source in Postgres table `sync_state`
   - Run as background task in ingestion service

9. **Write Tests**
   - Unit: chunker strategies with sample data
   - Integration: each ingestor with mock CLI output → verify memory entries created
   - Entity: verify cross-references between Jira ticket and GitLab MR

## TODO

- [ ] Create `services/ingestion/base.py` (abstract interface)
- [ ] Create `services/ingestion/chat.py`
- [ ] Create `services/ingestion/jira.py`
- [ ] Create `services/ingestion/gitlab.py`
- [ ] Create `services/ingestion/confluence.py`
- [ ] Create `services/ingestion/chunker.py`
- [ ] Create `services/ingestion/entity.py`
- [ ] Create `services/ingestion/scheduler.py`
- [ ] Modify `scripts/matrix-listener.py` to publish to Redis
- [ ] Create `services/ingestion/sync_state.py`
- [ ] Write unit + integration tests
- [ ] Run initial full sync and measure timing

## Success Criteria

1. Chat history from gchat-inbox.jsonl fully ingested with thread grouping
2. `memory_client.search("sprint blocker")` returns relevant Jira tickets
3. `memory_client.get_related("PROJ-123")` returns linked MR, chat threads, and Confluence pages
4. Incremental sync picks up new Jira tickets created since last run
5. New chat messages from matrix-listener trigger real-time ingestion via Redis

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| CLI tools not installed on Docker | High | High | Run ingestors on host (not in container) or install CLIs in container |
| Jira/GitLab API rate limits | Medium | Medium | Respect rate limits, exponential backoff, cache responses |
| Large Confluence spaces overwhelm embedding API | Low | Medium | Paginate, process in batches of 10 pages |
| Entity extraction false positives | Medium | Low | Conservative regex, validate entity existence before linking |

## Security Considerations

- Jira/GitLab/Confluence credentials managed by host CLI tools (already configured)
- Ingested content may contain sensitive code/tickets — same access boundary as user's local machine
- Redis has no auth (local Docker network only)
- Never embed or store actual source code diffs — only summaries and metadata
