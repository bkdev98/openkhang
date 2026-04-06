# Phase 3: Health Checker Update

**Priority:** High
**Status:** TODO

## Overview

Replace `check_ollama()` with `check_embedding_api()` that pings the external embedding provider.

## Files to Modify

- `services/dashboard/health_checker.py` — replace `check_ollama()` (L51-73), update `get_all_health()` (L85-93)

## Implementation Steps

1. Replace `check_ollama()` with `check_embedding_api()`:
   - If using external API: send a lightweight test embed request (single word) to verify connectivity
   - If Ollama fallback active: keep existing probe
   - Return `{"name": "embeddings", "status": "ok/error", ...}`

2. Update `get_all_health()`:
   - Rename `ollama_task` to `embedding_task`
   - Call `check_embedding_api()` instead of `check_ollama()`

## Success Criteria

- [ ] Dashboard health page shows "embeddings: ok" when API is reachable
- [ ] Dashboard health page shows "embeddings: error" with detail when API is down
- [ ] Ollama fallback path still works for health check
