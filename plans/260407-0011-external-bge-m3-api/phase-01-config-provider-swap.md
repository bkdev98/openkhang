# Phase 1: Config + Mem0 Provider Swap

**Priority:** Critical
**Status:** TODO

## Overview

Swap Mem0 embedder from `ollama` provider to `openai` provider with OpenRouter base URL. OpenRouter serves BGE-M3 via an OpenAI-compatible API, so Mem0's `openai` provider works with a `base_url` override.

## Key Insight

OpenRouter's embedding API is OpenAI-compatible. Mem0's `openai` embedder provider accepts `openai_base_url` to point at any OpenAI-compatible endpoint. No custom provider needed.

## Files to Modify

- `services/memory/config.py` — swap embedder config
- `.env.example` — replace `OLLAMA_BASE_URL` with `OPENROUTER_API_KEY`

## Implementation Steps

1. In `config.py` dataclass:
   - Replace `ollama_base_url: str` with `embedding_api_key: str = ""`
   - Add `embedding_api_url: str = ""` (for OpenRouter base URL)
   - Update `from_env()`: read `EMBEDDING_API_KEY` and `EMBEDDING_API_URL` (default: `https://openrouter.ai/api/v1`)
   - Remove `OLLAMA_BASE_URL` env var read

2. In `as_mem0_config()` embedder block:
   ```python
   "embedder": {
       "provider": "openai",
       "config": {
           "model": self.embedding_model,  # "BAAI/bge-m3" for OpenRouter
           "api_key": self.embedding_api_key,
           "openai_base_url": self.embedding_api_url,
           "embedding_dims": 1024,
       },
   },
   ```

3. Update `.env.example`:
   - Remove `OLLAMA_BASE_URL=http://localhost:11434`
   - Add `EMBEDDING_API_KEY=` (OpenRouter API key)
   - Add `EMBEDDING_API_URL=https://openrouter.ai/api/v1`
   - Change `EMBEDDING_MODEL=bge-m3` to `EMBEDDING_MODEL=BAAI/bge-m3` (OpenRouter model ID)

4. Keep backward compat: if `OLLAMA_BASE_URL` is set and `EMBEDDING_API_KEY` is not, fall back to Ollama provider (for existing local setups)

## Success Criteria

- [ ] `MemoryConfig.from_env()` loads new env vars
- [ ] `as_mem0_config()` returns `openai` provider config with OpenRouter URL
- [ ] Existing Ollama setups still work via fallback
- [ ] No dimension changes (stays 1024)

## Risk

- OpenRouter model ID format (`BAAI/bge-m3`) may differ from what Mem0 passes to OpenAI SDK. Need to verify.
