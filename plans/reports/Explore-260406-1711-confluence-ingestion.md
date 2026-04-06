# Confluence Ingestion Code Exploration Report

**Date:** 2026-04-06  
**Scope:** Thorough analysis of Confluence ingestor in services/ingestion/  
**Focus:** Bugs, missing imports, incomplete implementations, data flow

---

## Executive Summary

The Confluence ingestor is mostly well-structured with a clear pipeline: fetch → chunk → store. However, **a critical bug in the date filtering logic breaks incremental sync**, causing all pages to be re-indexed every hour regardless of the "since" parameter. Additionally, there are 5+ other bugs/incomplete implementations that reduce reliability for large teams and code-containing pages.

---

## 1. Confluence-Related Files Located

**Code:**
- `/Users/khanh.bui2/Projects/openkhang/services/ingestion/confluence.py` (331 lines)

**Configuration:**
- `/Users/khanh.bui2/Projects/openkhang/.env.example` (lines 15-20)

**Related Components:**
- `services/ingestion/base.py` (BaseIngestor abstract class)
- `services/ingestion/scheduler.py` (IngestionScheduler registration)
- `services/ingestion/chunker.py` (chunk_by_section, chunk_by_size)
- `services/ingestion/entity.py` (extract_and_store_entities)
- `services/memory/client.py` (MemoryClient with Mem0 + pgvector backend)

---

## 2. ConfluenceIngestor Class Complete Walkthrough

### Constructor & Config
```python
class ConfluenceIngestor(BaseIngestor):
    def __init__(
        self,
        memory_client: "MemoryClient",
        space_key: str | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> None:
```

Loads from environment:
- `CONFLUENCE_DOMAIN` — e.g., "myteam.atlassian.net" (required)
- `CONFLUENCE_USERNAME` — Atlassian account email (required)
- `CONFLUENCE_API_TOKEN` — API token (required)
- `CONFLUENCE_SPACE_KEY` — Space key to ingest (optional, defaults to all)
- `CONFLUENCE_API_PATH` — In .env.example but **NOT USED** (dead config)
- `CONFLUENCE_AUTH_TYPE` — In .env.example but **NOT USED** (dead config)

### Public Methods

**1. `async fetch_new(since: datetime | None) -> list[Document]`**
- Calls `_fetch_pages_via_api(since=since)` — primary path
- Falls back to `_run_atlassian_cli()` if REST API returns empty (rarely)
- Returns list of Document objects ready for chunking
- **BUG #1 here:** See section 3 below

**2. `def chunk(doc: Document) -> list[Chunk]`**
- Primary: `chunk_by_section(doc.content, delimiter="##")` splits on h2 headers
- Fallback: If ≤1 sections AND content > 500 chars, use `chunk_by_size(max_chars=2000)`
- Adds document metadata to each chunk: page_id, space_key, title
- Reasonable approach; handles both structured and unstructured Confluence content

**3. `async ingest(since: datetime | None) -> IngestResult`**
- Orchestrates full pipeline: fetch → chunk → store
- Checks config (CONFLUENCE_DOMAIN, CONFLUENCE_API_TOKEN) early; skips if missing
- For each document:
  - Chunks it
  - Stores each chunk via `memory.add_memory(content, metadata, agent_id="outward")`
  - Calls `extract_and_store_entities()` for Jira refs, GitLab refs, people
- Returns IngestResult with totals
- Clean error handling per document (continues on error)

### Private Helper Methods

**`_auth_header() -> str`**
- Constructs Base64-encoded "Basic username:token" header
- Standard pattern ✓

**`_api_get(path: str, params: dict) -> Any`**
- Makes authenticated HTTP GET to Confluence REST API v2
- URL format: `https://{domain}/wiki/api/v2{path}?{params}`
- Includes "Authorization: Basic ..." and "Accept: application/json"
- Timeout: 30 seconds
- Returns parsed JSON or None on error
- Graceful error handling ✓

**`_fetch_pages_via_api(since: datetime | None) -> list[dict]`**
- Builds query params: limit, sort=-last-modified, body-format=storage, space-key (optional)
- Calls `_api_get("/wiki/api/v2/pages", params)`
- **CONTAINS BUG #1** (see section 3)

**`_get_page_body(page_id: str) -> str`**
- Fetches full page body: `/wiki/api/v2/pages/{page_id}?body-format=atlas_doc_format`
- Attempts to extract from body.storage or body.atlas_doc_format
- Strips HTML tags with `_strip_html_tags()`
- **BUG #3 & #5 here** (see section 3)

**`_run_atlassian_cli(args: list[str]) -> list[dict]`**
- Executes `atlassian-cli` command and parses JSON output
- Handles FileNotFoundError (CLI not installed) gracefully
- **INCOMPLETE #1:** This code path is rarely used and likely broken

**`_page_to_document(page: dict) -> Document | None`**
- Extracts: page_id, title, space_key, body content
- Attempts inline body.storage first, falls back to `_get_page_body()` if empty
- Strips HTML and returns Document with metadata
- **BUG #3 & #6 here** (see section 3)

**`_strip_html_tags(html: str) -> str`**
- Simple regex: `re.sub(r"<[^>]+>", " ", html)`
- Replaces common entities: &nbsp;, &amp;, &lt;, &gt;, &quot;
- Collapses multiple spaces
- **BUG #5 here:** Strips ALL HTML including code blocks (see section 3)

---

## 3. Critical Bugs & Issues Found

### BUG #1: Date Filtering Logic is Broken (CRITICAL)

**Location:** Lines 112-121, `_fetch_pages_via_api()` method

**The Problem:**
```python
if since:
    filtered = []
    for page in results:
        version = page.get("version", {})
        updated = version.get("createdAt", "")
        if updated and updated >= since.isoformat():
            filtered.append(page)
        else:
            filtered.append(page)  # Include all when filtering is uncertain
    return filtered
```

**What's Wrong:**
- Both the `if` and `else` branches append the page
- The `since` parameter is **completely ignored**
- ALL pages are returned regardless of timestamp
- The comment "Include all when filtering is uncertain" suggests intent to be safe, but it defeats incremental sync

**Impact:**
- Incremental sync is non-functional
- Every hour, ALL pages are re-indexed into memory
- Wastes API calls and causes duplicate entries in semantic memory
- SyncStateStore timestamps are tracked but never actually used

**Expected Behavior:**
Only pages with `updated >= since` should be included.

**Fix:**
```python
if updated and updated >= since.isoformat():
    filtered.append(page)
# Remove the else clause entirely, or skip pages that don't match
```

**Severity:** CRITICAL — breaks core incremental sync feature

---

### BUG #2: String-Based Timestamp Comparison (HIGH)

**Location:** Line 117, `_fetch_pages_via_api()` method

**The Problem:**
```python
if updated and updated >= since.isoformat():
```

- `since` is a timezone-aware datetime from SyncStateStore (asyncpg returns TZ-aware)
- `updated` is a string from Confluence API response (format: "2024-01-15T10:30:45Z")
- String comparison works *if formats match exactly*, but is fragile:
  - If Confluence returns naive datetime (no Z suffix), comparison is unreliable
  - Different millisecond precision will cause mismatches
  - DST transitions might affect format

**Impact:**
- Timestamp filtering may silently fail
- Pages with close timestamps to the boundary may be inconsistently included/excluded

**Fix:**
Parse both as datetime objects before comparing:
```python
from datetime import datetime
if updated:
    updated_dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
    if updated_dt >= since:
        filtered.append(page)
```

**Severity:** HIGH — subtle data consistency issue

---

### BUG #3: Unnecessary Double Fetch of Page Body

**Location:** Lines 227-228, `_page_to_document()` method

**The Problem:**
```python
# If no inline body, fetch separately
if not content.strip():
    content = self._get_page_body(page_id)
```

- `_fetch_pages_via_api()` requests `body-format=storage` in params
- API response often includes full body inline
- If inline body is empty, it makes an extra HTTP call to fetch again
- This happens for every page where the inline body is not present

**Impact:**
- Extra API calls (2x for some pages)
- Slower ingestion
- Higher risk of hitting rate limits

**Fix:**
- Check API response structure to understand when body is missing inline
- Add a flag to control whether to fetch full body
- Consider lazy loading: only fetch body if needed for chunking

**Severity:** MEDIUM — performance issue, not correctness

---

### BUG #4: Hard-Coded Page Limit

**Location:** Line 28, `_DEFAULT_LIMIT = 20`

**The Problem:**
- ConfluenceIngestor is hardcoded to fetch max 20 pages per run
- Scheduler runs every 1 hour
- If a team updates >20 pages/hour, some are missed
- Not configurable, not documented

**Impact:**
- Large teams will miss pages during high-activity periods
- Silent failure (no error logged)

**Fix:**
Make it configurable:
```python
def __init__(
    self,
    memory_client: "MemoryClient",
    space_key: str | None = None,
    limit: int | None = None,
) -> None:
    self._limit = limit or int(os.getenv("CONFLUENCE_PAGE_LIMIT", "20"))
```

**Severity:** MEDIUM — impacts large teams

---

### BUG #5: HTML Code Blocks are Destroyed

**Location:** `_strip_html_tags()` function (lines 323-330)

**The Problem:**
```python
def _strip_html_tags(html: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", html)  # ← Removes ALL tags
    ...
```

- Confluence stores code in `<code>` or `<pre>` tags
- This regex removes them, leaving only the text
- Example: `<code>foo_bar()</code>` becomes `foo bar` (loses formatting)
- No distinction between structural HTML and semantic content

**Impact:**
- Code examples in Confluence are corrupted
- Code formatting is lost
- Function/variable names might be misunderstood by agent
- Jira key extraction might fail if they're in code blocks

**Fix:**
Preserve or convert code tags:
```python
def _strip_html_tags(html: str) -> str:
    import re
    # Convert code blocks to markdown
    html = re.sub(r'<code>([^<]+)</code>', r'`\1`', html)
    html = re.sub(r'<pre>([^<]+)</pre>', r'```\n\1\n```', html)
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", " ", html)
    ...
```

**Severity:** MEDIUM — data loss for code-heavy teams

---

### BUG #6: Misleading Comment

**Location:** Line 125-126

Comment says "plain text via REST" but the method returns HTML-stripped content, not plain text. This is correct behavior, just misleading comment. Minor documentation issue.

**Severity:** LOW — cosmetic

---

### INCOMPLETE #1: Atlassian-CLI Fallback is Untested

**Location:** Lines 144-167, `_run_atlassian_cli()` + lines 186-189 in `fetch_new()`

**The Problem:**
- `fetch_new()` only falls back to CLI if REST API returns empty results
- This is rare in practice, so CLI code is never exercised
- CLI code likely has issues and is deprecated
- Atlassian deprecated atlassian-cli in favor of REST API

**Impact:**
- If REST API fails, fallback won't work
- CLI-based sync is dead code
- No error handling strategy when REST API is unavailable

**Fix:**
- Remove atlassian-cli fallback entirely (it's deprecated)
- Or add proper error handling: if REST API fails, log and skip (don't fallback)

**Severity:** LOW-MEDIUM — defensive measure only

---

### INCOMPLETE #2: No Rate Limiting or Retry Logic

**Location:** Throughout `_api_get()` and document fetching

**The Problem:**
- Makes unlimited sequential API calls (20 pages × 2 fetches = 40 API calls per hour)
- Confluence Cloud has rate limits (~1000 requests/hour)
- No exponential backoff or retry logic
- No circuit breaker pattern

**Impact:**
- Risk of throttling during heavy sync periods
- If rate-limited, ingestion silently fails with no recovery

**Fix:**
- Add rate limiter or token bucket
- Implement exponential backoff on HTTP 429
- Add timeout-based retry logic

**Severity:** MEDIUM — defensive measure for production reliability

---

### INCOMPLETE #3: Dead Configuration in .env.example

**Location:** `.env.example` lines 17-18

```
CONFLUENCE_API_PATH=/rest/api              # NOT USED
CONFLUENCE_AUTH_TYPE=basic                 # NOT USED
```

These are listed in config but never referenced in `confluence.py`. They should be removed or implemented.

**Severity:** LOW — documentation debt

---

## 4. Data Flow: Confluence → Chunker → Memory Store

### Step 1: Fetch (ConfluenceIngestor.fetch_new)
1. Calls `_fetch_pages_via_api(since=since)` (primary)
2. REST API call: `GET /wiki/api/v2/pages?limit=20&sort=-last-modified&body-format=storage`
3. Returns list of page dicts with metadata
4. Fallback to `_run_atlassian_cli()` if empty (rarely)
5. Returns: `list[Document]`

### Step 2: Document Conversion (_page_to_document)
1. Extract page_id, title, spaceId
2. Get body from inline `body.storage` or `body.atlas_doc_format`
3. If empty, fetch full page body via `_get_page_body(page_id)`
4. Strip HTML tags to plain text
5. Build metadata: page_id, space_key, title, updated_at
6. Returns: `Document(source="confluence", doc_id=page_id, title, content, metadata)`

### Step 3: Chunk (ConfluenceIngestor.chunk)
1. Primary: Split by h2 headers using `chunk_by_section(content, delimiter="##")`
2. Fallback: If ≤1 sections found and content > 500 chars, use `chunk_by_size(max_chars=2000)`
3. Add document metadata to each chunk
4. Returns: `list[Chunk]` where Chunk = (text, metadata)

### Step 4: Store (ConfluenceIngestor.ingest)
For each chunk:
```python
await self.memory.add_memory(
    content=chunk.text,
    metadata={
        "source": "confluence",
        "doc_id": doc.doc_id,
        "title": doc.title,
        "page_id": ...,
        "space_key": ...,
        **chunk.metadata,
    },
    agent_id="outward",
)
```

### Step 5: Memory Backend (services/memory/client.py)
1. `MemoryClient.add_memory()` is async
2. Offloads to thread pool (Mem0 is sync library): `Mem0.add(content, agent_id, metadata)`
3. Mem0 embeddings: bge-m3 via Ollama (`EMBEDDING_MODEL` from .env)
4. Backend: pgvector in Postgres (vectors + metadata stored)
5. Returns: Mem0 memory ID

### Step 6: Entity Extraction (extract_and_store_entities)
1. Scans text for Jira keys (e.g., "VR-123")
2. Scans text for GitLab MR refs (e.g., "!42")
3. Extracts people from metadata (assignee, author, etc.)
4. Stores each as a separate memory via `memory.add_memory()`

**Final Result:** Confluence page chunks are indexed in pgvector, searchable by semantic similarity, with metadata tags for filtering.

---

## 5. Scheduler Integration

### Registration in scheduler.py

**Lines 69-80:**
```python
ingestors: dict[str, Any] = {
    "jira": JiraIngestor(self._memory),
    "gitlab": GitLabIngestor(self._memory),
    "confluence": ConfluenceIngestor(self._memory),  # ← Created here
    "chat": ChatIngestor(self._memory),
}
```

**Lines 25-30 (Default Intervals):**
```python
_DEFAULT_INTERVALS: dict[str, int] = {
    "jira": 5 * 60,        # 5 minutes
    "gitlab": 5 * 60,      # 5 minutes
    "confluence": 60 * 60, # 1 hour
    "code": 10 * 60,       # 10 minutes
    "chat": 0,             # realtime via Redis
}
```

### Polling Loop (scheduler._poll_loop)

For Confluence, the scheduler:
1. Calls `await self._sync.get_last_synced("confluence")` → gets previous timestamp
2. Calls `await ingestor.ingest(since=previous_timestamp)` → BUG #1 here!
3. Receives `IngestResult(source, total, ingested, skipped, errors)`
4. Updates SyncStateStore: `await self._sync.update_synced("confluence", now, count=ingested)`
5. Waits 1 hour, repeats

**Issue:** Due to BUG #1, the `since` parameter is ignored, so all pages are re-indexed every hour.

---

## 6. Configuration Review

### Required Environment Variables
```
CONFLUENCE_DOMAIN=your-confluence.example.com  # ✓ Used
CONFLUENCE_USERNAME=your.username              # ✓ Used
CONFLUENCE_API_TOKEN=                          # ✓ Used
CONFLUENCE_SPACE_KEY=                          # ✓ Used (optional)
```

### Unused Configuration (Dead Code)
```
CONFLUENCE_API_PATH=/rest/api                  # ✗ Not referenced
CONFLUENCE_AUTH_TYPE=basic                     # ✗ Not referenced
```

These should be removed from `.env.example` or implemented.

---

## 7. Import Analysis

**All imports are correct:**
- ✓ `base64, json, os, subprocess, urllib, datetime, typing` (stdlib)
- ✓ `.base, .chunker, .entity` (local imports)
- ✓ `TYPE_CHECKING` pattern for MemoryClient (correct to avoid circular imports)

**No missing imports.**

**Runtime dependencies (not checked in file):**
- Mem0 library (imported via MemoryClient)
- asyncpg (imported in sync_state.py at module level)
- Ollama service (for embeddings)
- Postgres with pgvector extension

---

## 8. Missing Error Handling

**Areas with potential issues:**
1. HTTP timeout (30s) — reasonable, but no retry logic
2. Malformed JSON from API — caught and logged ✓
3. Bad timestamp format — no validation (BUG #2)
4. Missing page_id — handled (returns None) ✓
5. Empty content — fallback to title ✓
6. Entity extraction failures — logged per entity ✓

**Overall:** Error handling is reasonable but not robust for production.

---

## 9. Unresolved Questions

1. Does the Confluence REST API v2 always return body inline with `body-format=storage`, or only sometimes?
2. What's the exact rate limit on Confluence Cloud API per hour?
3. Should the page limit be configurable or left as 20?
4. Is there a reason atlassian-cli fallback exists if it's never used?
5. Do we need to support pagination for >20 pages per sync?

---

## Summary Table: Bugs & Severity

| # | Type | Severity | Location | Impact |
|---|------|----------|----------|--------|
| 1 | Logic Error | CRITICAL | Line 112-121 | Incremental sync broken |
| 2 | Timestamp Comparison | HIGH | Line 117 | Fragile date filtering |
| 3 | Double Fetch | MEDIUM | Line 227-228 | Extra API calls |
| 4 | Hard-Coded Limit | MEDIUM | Line 28 | Misses pages on large teams |
| 5 | HTML Code Loss | MEDIUM | _strip_html_tags() | Corrupts code blocks |
| 6 | Misleading Comment | LOW | Line 125 | Documentation debt |
| I1 | Dead Fallback | LOW-MEDIUM | Line 186-189 | Untested code path |
| I2 | No Rate Limiting | MEDIUM | Throughout | Production risk |
| I3 | Dead Config | LOW | .env.example | Documentation debt |

---

## Recommendations

### Priority 1 (Fix Immediately)
- Fix BUG #1: Remove the `else` clause in date filtering

### Priority 2 (Fix Soon)
- Fix BUG #2: Parse timestamps as datetime, not strings
- Fix BUG #5: Preserve code blocks in HTML stripping

### Priority 3 (Nice to Have)
- Make page limit configurable
- Add rate limiting and retry logic
- Remove atlassian-cli fallback (deprecated)
- Remove dead config from .env.example

### Testing
Would benefit from:
- Unit test for date filtering with various timestamps
- Integration test with real Confluence instance
- Test for >20 pages per hour scenario
- Test for pages with code blocks

---

## Conclusion

The Confluence ingestor is well-structured and mostly functional, but **BUG #1 (broken incremental sync) is a critical issue** that should be fixed immediately. The other bugs are lower priority but worth addressing for robustness and performance.

