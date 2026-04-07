# Phase 6: Memory & Knowledge Drop Page

**Priority:** Medium
**Status:** Complete

## Overview

Browse/search Mem0 memories, filter by type, delete entries. Knowledge drop form for manual text/file ingestion.

## Related Code Files

**Modify:**
- `services/dashboard/app.py` — add memory + knowledge endpoints

**Create:**
- `services/dashboard/memory_services.py` — Mem0 search, list, delete + knowledge ingest adapter
- `services/dashboard/templates/pages/memory.html` — search + filters + results + knowledge drop
- `services/dashboard/templates/partials/memory_card.html` — single memory entry

## Implementation Steps

1. Create memory_services.py:
   - `search_memories(query, type_filter, limit)` — search Mem0 via MemoryClient
   - `delete_memory(memory_id)` — delete from Mem0
   - `ingest_text(text, source_label)` — chunk + embed + store via MemoryClient
   - `ingest_file(file_bytes, filename, source_label)` — extract text from file, then ingest

2. Add API endpoints:
   - `GET /api/memory/search?q=&type=&limit=20` — search memories
   - `DELETE /api/memory/{id}` — delete memory
   - `POST /api/memory/ingest` — ingest text or file (multipart form)

3. Create memory_card.html: type badge (colored), text preview (3 lines truncated), source, timestamp, delete button with confirmation

4. Create memory.html: search bar (debounced), type filter pills (All/Semantic/Episodic/Working), results list, knowledge drop section at bottom

5. Knowledge drop: textarea for text + file drop zone (vanilla JS drag-and-drop), source label input, ingest button. File size validation (5MB max, text/pdf/md).

## Todo

- [x] Create memory_services.py with search, delete, ingest methods
- [x] Add /api/memory/* endpoints to app.py
- [x] Create memory_card.html partial
- [x] Create memory.html page with search + filters + knowledge drop
- [x] Implement file drag-and-drop upload
- [x] Add delete confirmation dialog
- [x] Verify Mem0 integration works

## Success Criteria

- Search returns relevant memories with type badges
- Type filter narrows results
- Delete removes memory (with confirmation)
- Text paste ingests successfully
- File upload works for text/pdf/md under 5MB
