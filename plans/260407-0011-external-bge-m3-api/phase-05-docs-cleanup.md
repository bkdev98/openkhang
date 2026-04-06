# Phase 5: Docs + Cleanup

**Priority:** Medium
**Status:** TODO

## Overview

Update all documentation and docker-compose comments to reflect external API instead of Ollama.

## Files to Modify

- `docker-compose.yml` — remove Ollama comment block (L50-53)
- `README.md` — update architecture diagram, prerequisites, services table, quick start
- `docs/system-architecture.md` — update embedding layer references
- `docs/deployment-guide.md` — update setup instructions
- `docs/codebase-summary.md` — update module descriptions
- `docs/project-overview-pdr.md` — update tech stack references
- `docs/project-roadmap.md` — mark this task as done

## Key Changes

- Prerequisites: remove Ollama row, add "OpenRouter API key" row
- Services table: replace `Ollama | 11434 | bge-m3 embeddings` with `OpenRouter API | external | bge-m3 embeddings`
- Architecture diagram: `Ollama (native)` → `OpenRouter API`
- All "local bge-m3 via Ollama" → "bge-m3 via OpenRouter API"

## Success Criteria

- [ ] No stale Ollama references in user-facing docs
- [ ] README accurately describes new setup
- [ ] Deployment guide has correct setup steps
