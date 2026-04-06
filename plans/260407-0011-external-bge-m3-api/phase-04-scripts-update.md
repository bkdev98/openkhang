# Phase 4: Scripts Update

**Priority:** High
**Status:** TODO

## Overview

Remove Ollama install/pull/verify steps from setup and onboarding scripts. Replace with API key validation.

## Files to Modify

- `scripts/setup-memory.sh` — remove Ollama CLI check, serve, pull, verify (L25-26, L89-134)
- `scripts/onboard.sh` — remove `ollama` from prereqs (L36), remove pull step (L116-131)

## Implementation Steps

1. `scripts/setup-memory.sh`:
   - Remove `OLLAMA_URL` and Ollama-specific vars
   - Remove Ollama install check, `ollama serve`, `ollama pull` blocks
   - Replace embed verification with: check `EMBEDDING_API_KEY` is set, optionally curl the API
   - Keep Docker (postgres, redis) setup unchanged

2. `scripts/onboard.sh`:
   - Remove `ollama` from `for cmd in docker ollama python3` prereq loop
   - Remove Step 5 (Ollama start + bge-m3 pull)
   - Add: check `EMBEDDING_API_KEY` is set in `.env`, warn if missing
   - Update summary output line

## Success Criteria

- [ ] `bash scripts/onboard.sh` works without Ollama installed
- [ ] `bash scripts/setup-memory.sh` works without Ollama installed
- [ ] Scripts warn if `EMBEDDING_API_KEY` is missing from `.env`
