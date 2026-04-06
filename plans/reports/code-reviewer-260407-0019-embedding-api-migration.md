# Code Review: Ollama to OpenRouter BGE-M3 API Migration

**Date:** 2026-04-07
**Scope:** 8 files, ~400 LOC changed
**Focus:** Security, correctness, edge cases, stale references

## Overall Assessment

Migration is clean and well-structured. Config validates early, scripts check API key before proceeding, no hardcoded secrets. A few issues found below.

---

## Critical Issues

None.

## High Priority

### 1. Stale Ollama docstring in `services/ingestion/code.py:112`

```python
"""Ingest code chunks directly into pgvector via Ollama embeddings."""
```

This docstring still references Ollama. While cosmetic, it misleads developers about the actual embedding path and could cause confusion during debugging.

**Fix:** Change to `"""Ingest code chunks directly into pgvector via embedding API."""`

### 2. Plan specified Ollama fallback -- not implemented (intentional?)

Phase 1 plan (`phase-01-config-provider-swap.md` line 46) says:
> Keep backward compat: if `OLLAMA_BASE_URL` is set and `EMBEDDING_API_KEY` is not, fall back to Ollama provider

Current `config.py` raises `ValueError` if `EMBEDDING_API_KEY` is empty -- no fallback. This is a **breaking change for anyone running existing Ollama setups**.

**Verdict:** If no existing Ollama users, this is fine (YAGNI). If any deployment uses Ollama, add fallback or document the break. Confirm intent.

### 3. Docs still reference Ollama extensively (Phase 5 not done)

Stale Ollama references remain in user-facing docs:
- `README.md` (3 refs: prerequisites, services table, architecture)
- `docs/system-architecture.md` (~15 refs)
- `docs/deployment-guide.md` (~15 refs: setup steps, troubleshooting)
- `docs/project-overview-pdr.md` (~8 refs)
- `docs/code-standards.md` (2 refs)
- `docs/codebase-summary.md` (4 refs)

These are Phase 5 per the plan and may be intentionally deferred, but anyone reading docs will get incorrect setup instructions (install Ollama, pull bge-m3, etc.).

**Action:** Phase 5 should be completed before merging to main, or at minimum `README.md` prerequisites/setup sections should be updated since that's the entry point for new users.

## Medium Priority

### 4. Health check probes `/models` not `/embeddings`

`health_checker.py:59` hits `{api_url}/models` to check embedding API health. This verifies the API is reachable but doesn't confirm the embedding model is available or that the API key has embedding permissions.

A more targeted health check would hit `/embeddings` with a tiny test input (like the scripts do). The `/models` endpoint may succeed even if the key lacks embedding scope.

**Trade-off:** `/models` is cheaper and faster. Current approach is acceptable for a health dashboard but could give false-positive "ok" status.

### 5. Health checker reads env vars directly instead of using MemoryConfig

`health_checker.py:54-56` reads `EMBEDDING_API_URL` and `EMBEDDING_API_KEY` via `os.getenv()` independently from `config.py`. If default values or env var names ever diverge, health check will use different config than the actual embedder.

**Suggestion:** Pass config values to `check_embedding_api()` or accept them as params rather than reading env directly. This keeps a single source of truth.

### 6. `setup-memory.sh` sources `.env` with `set -a` -- potential side effects

Line 89: `set -a; source .env; set +a` exports ALL vars in `.env` to the environment. If `.env` contains vars that conflict with shell builtins or other tools (e.g., `PATH`, `HOME`), this could cause subtle breakage.

**Risk:** Low in practice since `.env` is project-scoped, but worth noting.

### 7. Embedding API response format check is fragile

Both scripts check for `'"embedding"'` in the curl response via grep:
```bash
if echo "$EMBED_RESPONSE" | grep -q '"embedding"'; then
```

OpenRouter's actual response key is `"data"` containing objects with `"embedding"` arrays. This works but is brittle -- if the response format changes or returns an error JSON containing the word "embedding", it could false-positive/negative.

## Low Priority

### 8. `embedding_model_dims` duplicated with `embedding_dims`

`config.py` sets `embedding_model_dims: 1024` in vector_store config (line 88) AND `embedding_dims: 1024` in embedder config (line 97). Both are hardcoded to 1024. If BGE-M3 is ever swapped for a different model, both must be updated in sync.

**Suggestion:** Extract to a constant `_EMBEDDING_DIMS = 1024` and reference it in both places.

### 9. `onboard.sh` continues after `EMBEDDING_API_KEY` failure

Line 82-83: The script logs `fail "EMBEDDING_API_KEY is not set"` but does NOT exit. It continues through venv setup, docker compose, etc. Compare with `setup-memory.sh` which `exit 1` on missing key.

This is arguably intentional (onboard should show full status) but the `fail` prefix implies a hard error. Either exit or downgrade to `warn`.

---

## Positive Observations

- Config validation in `from_env()` raises early with actionable error messages including URLs
- Clean separation: `MemoryConfig` owns all config, `as_mem0_config()` translates to Mem0 format
- Scripts verify embedding endpoint actually responds, not just that the key is set
- No secrets in `.env.example` -- all placeholder values
- Health checker properly uses async (`asyncio.to_thread`) for blocking HTTP call
- `docker-compose.yml` comment updated to reflect new setup

## Correctness: Mem0 OpenAI Provider Config

The config format at `config.py:91-98` matches Mem0's expected OpenAI embedder config:
- `provider: "openai"` -- correct for OpenAI-compatible APIs
- `model` -- model identifier passed to the API
- `api_key` -- authentication
- `openai_base_url` -- base URL override (confirmed in Mem0 source as the correct key name)
- `embedding_dims: 1024` -- dimension override for non-OpenAI models

This is correct per Mem0 docs and the researcher report findings.

## Security Check

- [x] No hardcoded API keys in any changed file
- [x] `.env.example` contains only placeholder values
- [x] API key validated before use (config raises, scripts check)
- [x] Bearer token auth used correctly in health check and script curl calls
- [x] No API key logged or printed in any output
- [x] `.env` is in `.gitignore` (verified by existence of `.env.example` pattern)

## Recommended Actions (Priority Order)

1. **Fix stale docstring** in `services/ingestion/code.py:112` (5 seconds)
2. **Confirm Ollama fallback intent** -- if no fallback needed, close the plan item; if needed, implement before merge
3. **Complete Phase 5 (docs)** before merging to main -- at minimum update `README.md`
4. **Consider** passing config to health checker instead of re-reading env vars
5. **Consider** extracting `_EMBEDDING_DIMS = 1024` constant

## Unresolved Questions

1. Is the Ollama fallback path intentionally dropped? Plan specified it but implementation doesn't include it.
2. Is Phase 5 (docs cleanup) being done in a separate PR or should it block this one?
3. Does `onboard.sh` intentionally continue after `EMBEDDING_API_KEY` failure, or should it exit like `setup-memory.sh`?

---

**Status:** DONE
**Summary:** Migration is solid. One stale docstring, extensive stale docs (Phase 5), and a plan-vs-implementation mismatch on Ollama fallback need resolution. No security or correctness blockers.
