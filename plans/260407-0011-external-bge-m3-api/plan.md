# Plan: Switch BGE-M3 from Local Ollama to External API

**Date:** 2026-04-07
**Branch:** `feat/external-embedding-api`
**Status:** Draft

## Goal

Replace local Ollama BGE-M3 embeddings with OpenRouter BGE-M3 API. Same model, same dimensions (1024), zero re-embedding. Removes Ollama as a runtime dependency.

## Why

- Ollama consumes CPU/RAM on local machine for <$0.01/month of work
- Weaker devices can't run BGE-M3 locally
- OpenRouter serves the same model via API at $0.01/M tokens (~free at our 470-memory scale)

## Decision: OpenRouter BGE-M3

- Same model = identical embeddings = no re-embedding needed
- 1024-dim = no pgvector schema change
- $0.01/M tokens, free tier available
- OpenAI-compatible API = Mem0's `openai` provider works with `base_url` override

## Phases

| # | Phase | Status | Files |
|---|-------|--------|-------|
| 1 | Config + Mem0 provider swap | TODO | `services/memory/config.py`, `.env.example` |
| 2 | Remove dead code + Ollama dep | TODO | `services/ingestion/code.py`, `services/requirements.txt` |
| 3 | Health checker update | TODO | `services/dashboard/health_checker.py` |
| 4 | Scripts update | TODO | `scripts/onboard.sh`, `scripts/setup-memory.sh` |
| 5 | Docs + cleanup | TODO | `docker-compose.yml`, `README.md`, `docs/*` |

## Research

- [Provider comparison](../reports/researcher-260406-2351-mem0-embedding-providers.md)
- [BGE-M3 vs text-embedding-3-small](../reports/researcher-260406-2356-bge-m3-vs-openai-te3-small.md)
- [Voyage AI vs BGE-M3](../reports/researcher-260407-0005-voyage-ai-vs-bge-m3-multilingual.md)
- [Multimodal embeddings](../reports/researcher-260407-0005-multimodal-embeddings-rag.md)
