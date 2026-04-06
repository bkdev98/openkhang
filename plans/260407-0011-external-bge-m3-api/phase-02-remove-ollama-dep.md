# Phase 2: Remove Dead Code + Ollama Dependency

**Priority:** High
**Status:** TODO

## Overview

Clean up unused Ollama references in runtime code and remove the `ollama` pip package.

## Files to Modify

- `services/ingestion/code.py` — remove dead env var reads (L125-126)
- `services/requirements.txt` — remove `ollama>=0.4.0`
- `services/memory/client.py` — update docstring comment (L29)
- `services/dashboard/dashboard_services.py` — update docstring (L51)

## Implementation Steps

1. `services/ingestion/code.py`: delete lines 125-126 (unused `ollama_url` and `embed_model` vars)
2. `services/requirements.txt`: remove `ollama>=0.4.0`, add `openai>=1.0.0` (needed by Mem0's openai embedder provider)
3. Update docstring comments referencing "Ollama" in `client.py` and `dashboard_services.py`

## Success Criteria

- [ ] No runtime references to `ollama` package remain
- [ ] `pip install -r requirements.txt` succeeds without ollama
- [ ] Grep for `ollama` in `services/` returns only config.py fallback path
