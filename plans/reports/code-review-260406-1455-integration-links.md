# Integration Link Review: Digital Twin System

**Date:** 2026-04-06
**Scope:** End-to-end data flow from Matrix listener through agent pipeline to dashboard
**Files reviewed:** 40+ files across services/agent, services/dashboard, services/memory, services/workflow, services/ingestion, config/, scripts/

---

## Critical Issues

### Issue 1: `sender` vs `sender_id` field name mismatch in agent_relay → pipeline

**Severity:** Critical
**File(s):** `services/dashboard/agent_relay.py:103`, `services/agent/pipeline.py:153`, `services/agent/prompt_builder.py:114`
**Problem:** agent_relay constructs the event dict with key `"sender"` (line 103), but the pipeline reads `event.get("sender_id", "")` (line 153) for sender relationship context, and prompt_builder reads `event.get("sender_id", "unknown")` (line 114) for message headers. The field `sender_id` is never set by agent_relay; instead it uses `"sender"` key. This means:
- Sender relationship context is **never fetched** (sender_id is always empty string)
- Outward prompts always show `[Message from unknown ...]`
- Confidence penalty MODIFIER_UNKNOWN_SENDER (-0.30) is always applied, artificially depressing scores

**Fix:** In `agent_relay.py:103`, change:
```python
"sender": payload.get("sender_id", sender_id),
```
to:
```python
"sender_id": payload.get("sender_id", sender_id),
```
Or add both `sender` and `sender_id` keys for compatibility.

---

### Issue 2: twin_chat creates new pipeline + connections per request (resource leak)

**Severity:** Critical
**File(s):** `services/dashboard/twin_chat.py:20-38`
**Problem:** Every `/api/chat` POST creates a brand new `AgentPipeline.from_env()`, calls `connect()` (opens Mem0 + asyncpg pools), processes one question, then `close()`. This means:
- New Postgres connection pool per request (pool creation is expensive)
- New Mem0 instance per request (blocking init offloaded to thread pool)
- Under moderate load, connection pool exhaustion is likely
- If `close()` throws, pools leak

**Fix:** Share a single pipeline instance via the DashboardServices lifespan, same as the agent_relay pipeline. Initialize once in lifespan, pass to twin_chat.

---

### Issue 3: Workflow trigger event type mismatch — workflows never fire

**Severity:** Critical
**File(s):** `config/workflows/chat-to-jira.yaml:4`, `services/workflow/workflow_engine.py:320-321`, `services/dashboard/agent_relay.py`
**Problem:** The chat-to-jira workflow triggers on `event: chat_message`, but the workflow engine checks `event.get("type") or event.get("event_type", "")`. The events produced by the agent_relay have `event_type: "message.received"` (from the events table), not `chat_message`. The workflow engine is never called from agent_relay at all — there is no integration point. Workflows are defined but never wired into the main event processing loop.

**Fix:** Either:
1. Add workflow engine invocation to agent_relay's event processing loop
2. Align the trigger event type with what the pipeline actually produces
3. Create a separate background task that polls events and feeds them to the workflow engine

---

## High Priority

### Issue 4: Duplicate Postgres connection pools for same database

**Severity:** High
**File(s):** `services/dashboard/app.py:38-49`, `services/dashboard/agent_relay.py:48-49`
**Problem:** DashboardServices opens one pool. agent_relay creates a second pool inside DraftQueue (line 48-49: `drafts = DraftQueue(config.database_url); await drafts.connect()`), and a third pool inside MemoryClient's EpisodicStore. That's 3 separate pools to the same Postgres instance (5 connections each = 15 connections minimum). For a local dev setup with `max_connections=100` this works, but it's wasteful and complicates connection management.

**Fix:** Pass the existing pool from DashboardServices into DraftQueue and EpisodicStore, or use a shared pool factory.

---

### Issue 5: SSE `last_ts` is ISO string; `get_recent_events(since=)` parses it — but timezone may be lost

**Severity:** High
**File(s):** `services/dashboard/app.py:97-110`, `services/dashboard/dashboard_services.py:183`
**Problem:** `_normalise_event` converts `created_at` to ISO string via `.isoformat()` (line 275). This ISO string is stored as `last_ts`. On subsequent polls, `get_recent_events(since=last_ts)` calls `datetime.fromisoformat(since)`. If the Postgres column returns a timezone-aware datetime, `.isoformat()` includes `+00:00`. But `datetime.fromisoformat()` with `+00:00` on Python <3.11 may lose timezone info, creating a naive datetime. asyncpg will reject a naive datetime for `timestamptz` comparison on some configurations.

**Fix:** Ensure consistent timezone handling — always produce offset-aware datetimes. Add `.replace(tzinfo=timezone.utc)` as fallback when parsing.

---

### Issue 6: Ingestion scheduler is never started by the dashboard

**Severity:** High
**File(s):** `services/dashboard/app.py` (lifespan), `services/ingestion/scheduler.py`
**Problem:** The dashboard lifespan starts `tail_inbox` and `run_agent_relay`, but never starts the IngestionScheduler. The scheduler (which handles Jira, GitLab, Confluence periodic ingestion and chat Redis realtime ingestion) is defined but has no integration point. It's never called from anywhere in the running system.

**Fix:** Either start the scheduler as a background task in the dashboard lifespan, or run it as a separate process. Add to lifespan:
```python
from services.ingestion.scheduler import IngestionScheduler
scheduler = IngestionScheduler(memory_client, sync_store)
await scheduler.start()
```

---

### Issue 7: `audit_log.params` and `audit_log.result` stored as TEXT but schema is JSONB

**Severity:** High
**File(s):** `services/workflow/audit_log.py:60-66`, `services/memory/schema.sql:76-77`
**Problem:** `audit_log.py:60` passes `json.dumps(params)` and `json.dumps(result)` as Python strings to asyncpg. The schema defines these columns as JSONB. asyncpg expects either a Python dict (auto-serialized) or a string with explicit `::jsonb` cast. Without the cast, asyncpg will fail with a type mismatch error: `cannot convert str to jsonb`.

**Fix:** Either:
- Pass dicts directly (remove `json.dumps`)
- Or add `$4::jsonb, $5::jsonb` casts to the SQL (like episodic.py does)

---

### Issue 8: `workflow_persistence.save_instance` passes `context` as JSON string, schema expects JSONB

**Severity:** High
**File(s):** `services/workflow/workflow_persistence.py:48-68`, `services/memory/schema.sql:57-58`
**Problem:** Same pattern as Issue 7. `json.dumps(instance.context)` and `json.dumps(instance.context.get("event", {}))` produce strings, but `context JSONB` and `trigger_event JSONB` columns need explicit casts or dict values. Will fail at runtime with asyncpg type error.

**Fix:** Add `::jsonb` casts to `$4` and `$5` in the INSERT/UPSERT SQL, or pass dicts directly.

---

## Medium Priority

### Issue 9: `_log_event` only logs `auto_sent` or `drafted` — ignores `inward_response` and `error`

**Severity:** Medium
**File(s):** `services/agent/pipeline.py:303-306`
**Problem:** The event_type assigned is either `EPISODIC_TYPE_AGENT_REPLY` (auto_sent) or `EPISODIC_TYPE_DRAFT_QUEUED` (everything else, including errors and inward responses). Inward responses and errors shouldn't be logged as "draft queued" since no draft was created.

**Fix:** Add explicit handling:
```python
if result.action == "auto_sent":
    event_type = EPISODIC_TYPE_AGENT_REPLY
elif result.action == "drafted":
    event_type = EPISODIC_TYPE_DRAFT_QUEUED
elif result.action == "error":
    event_type = "agent.reply.error"
else:
    event_type = "agent.reply.inward"
```

---

### Issue 10: Workflow `context` column stored as JSON string on read — not parsed back on load

**Severity:** Medium
**File(s):** `services/workflow/workflow_persistence.py:131-135`
**Problem:** `_row_to_instance` handles `context` being a `str` by parsing with `json.loads`. However, asyncpg automatically deserializes JSONB columns into Python dicts. This means the `isinstance(context, str)` branch may never execute, OR if the save is using string-encoded JSON (per Issue 8), the read path may receive a string-inside-a-dict. The code is fragile due to the save/load asymmetry.

**Fix:** Fix the save path (Issue 8) to pass dicts directly. The load path will then always receive a dict from asyncpg, simplifying the code.

---

### Issue 11: Chat ingestor re-reads entire JSONL file on every ingest call

**Severity:** Medium
**File(s):** `services/ingestion/chat.py:63-76`, `services/ingestion/chat.py:166-178`
**Problem:** `ChatIngestor.ingest()` opens the entire JSONL file and reads all lines, then filters by `since_ms`. As the inbox file grows, this becomes O(n) on every ingest cycle. For a busy chat with thousands of messages per day, this degrades.

**Fix:** Track file offset (byte position) in sync_state so that subsequent reads can seek to the last position. Or truncate/rotate the inbox file after ingestion.

---

### Issue 12: SSE feed HTML injection — no escaping of event data

**Severity:** Medium (security)
**File(s):** `services/dashboard/templates/index.html:133-139`
**Problem:** The SSE event handler builds HTML by string concatenation from event data (`source`, `etype`, `actor`) without HTML-escaping. If an attacker sends a Matrix message with a crafted sender name containing `<script>`, it would be injected into the feed. The HTMX `sse-swap` replaces innerHTML with the constructed HTML.

**Fix:** Escape values before injecting into HTML:
```javascript
function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
// Then use esc(source), esc(etype), esc(actor) in the template
```

---

### Issue 13: Draft card `submitEdit` function redefined on every card render

**Severity:** Medium
**File(s):** `services/dashboard/templates/partials/draft_card.html:70-84`
**Problem:** The `<script>` block containing `submitEdit()` is included inside the `draft_card.html` partial, which is rendered inside a `{% for %}` loop. Every card re-declares the same function. While JavaScript silently overwrites it, this is wasteful and the function should be defined once.

**Fix:** Move `submitEdit` to the base template or a static JS file. Or use `hx-include` with a hidden textarea instead of manual JS.

---

### Issue 14: `base.html` template assumed but not reviewed — HTMX SSE extension may be missing

**Severity:** Medium
**File(s):** `services/dashboard/templates/index.html:1` (`{% extends "base.html" %}`)
**Problem:** `index.html` uses `hx-ext="sse"` and `sse-connect`/`sse-swap` which require the HTMX SSE extension. If `base.html` doesn't include the SSE extension JS file, the feed will silently fail with no error. Could not verify — `base.html` was not in the file list.

**Fix:** Verify `base.html` includes both htmx.js and the htmx-sse extension.

---

## Low Priority

### Issue 15: Confidence thresholds config path is relative to file location, fragile in Docker

**Severity:** Low
**File(s):** `services/agent/confidence.py:20`
**Problem:** `CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "confidence_thresholds.yaml"` works when the working directory is the project root, but breaks if the module is installed as a package or run from a different location. The graceful fallback to defaults mitigates the risk.

**Fix:** Use an environment variable for config path with the current path as default.

---

### Issue 16: WorkflowEngine not connected to ingestion scheduler or agent pipeline

**Severity:** Low (design gap, not a runtime bug)
**File(s):** `services/workflow/workflow_engine.py`, `services/ingestion/scheduler.py`, `services/dashboard/agent_relay.py`
**Problem:** The workflow engine is fully implemented but has no consumer. No code in the system calls `engine.handle_event()`. The ingestion scheduler doesn't invoke workflows. The agent_relay doesn't invoke workflows. The dashboard has no endpoint for workflow management. This is a complete subsystem with no integration.

**Fix:** Wire workflows into the event processing loop. Likely add to agent_relay after pipeline processing:
```python
# After pipeline.process_event()
await workflow_engine.handle_event(event)
```

---

### Issue 17: `_last_processed` in agent_relay is module-level mutable state

**Severity:** Low
**File(s):** `services/dashboard/agent_relay.py:22`
**Problem:** Using module-level `global _last_processed` works in a single-worker setup but would break with multiple uvicorn workers (each worker has its own copy). For single-worker dev mode this is fine.

**Fix:** Store last-processed timestamp in Postgres (e.g., sync_state table) for multi-worker resilience.

---

## Summary

| Severity | Count | Key themes |
|----------|-------|-----------|
| Critical | 3 | sender field mismatch, resource leak in twin_chat, workflows never fire |
| High | 5 | duplicate pools, JSONB type errors, scheduler not started, timezone handling |
| Medium | 6 | episodic logging, XSS in SSE feed, JSONL re-read, script duplication |
| Low | 3 | config paths, module-level state, design gaps |

### Most impactful fixes (effort vs value):
1. **Issue 1** (sender/sender_id) — 1-line fix, restores sender context + correct confidence scoring
2. **Issue 7+8** (JSONB casts) — 2 files, prevents runtime crashes in workflow engine
3. **Issue 2** (twin_chat pool leak) — moderate refactor, prevents connection exhaustion
4. **Issue 12** (XSS in SSE) — 5-line JS fix, closes injection vector

### Unresolved Questions
- Does `base.html` include the HTMX SSE extension? (Issue 14)
- Is the ingestion scheduler intended to run as a separate process or inside the dashboard? (Issue 6)
- Are workflows intended to be wired in during this phase, or a future phase? (Issue 3/16)

---

**Status:** DONE
**Summary:** Found 17 integration issues across the digital twin system. 3 critical: sender field key mismatch silently breaks sender context lookup and confidence scoring; twin_chat leaks connection pools on every request; workflow engine is fully built but never invoked. 5 high: JSONB type mismatches will crash workflow persistence, ingestion scheduler is never started, timezone handling may break SSE polling.
**Concerns:** The sender_id mismatch (Issue 1) means every outward reply is penalized -0.30 confidence and shows "unknown" sender in prompts — this has likely been affecting all outward pipeline behavior since initial implementation.
