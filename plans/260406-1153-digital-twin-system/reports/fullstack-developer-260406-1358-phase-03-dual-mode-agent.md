# Phase Implementation Report

## Executed Phase
- Phase: phase-03-dual-mode-agent
- Plan: /Users/khanh.bui2/Projects/openkhang/plans/260406-1153-digital-twin-system
- Status: completed

## Files Modified / Created

### New package: `services/agent/`
| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 22 | Package exports |
| `llm_client.py` | 135 | Claude API client, structured JSON output parsing, graceful fallback on parse failure |
| `classifier.py` | 113 | Mode (outward/inward) + intent classification via regex patterns |
| `prompt_builder.py` | 140 | System prompt assembly: templates + RAG context + style examples injection |
| `confidence.py` | 120 | Score 0–1 with modifiers (memories, deadline risk, unknown sender, CJK mismatch); per-room thresholds |
| `draft_queue.py` | 155 | asyncpg CRUD on `draft_replies` table; add/get/approve/reject/edit_and_approve |
| `matrix_sender.py` | 110 | Matrix client/v3 PUT send, thread reply support, per-room rate limiting (5/min) |
| `pipeline.py` | 185 | Main orchestrator: classify → RAG → prompt → LLM → confidence → route → episodic log |
| `prompts/outward_system.md` | 38 | Persona prompt: Khanh Bui, Vinglish style, hard rules, uncertainty phrases |
| `prompts/inward_system.md` | 35 | Assistant prompt: openkhang, concise/cited output, tier reference |

### New config: `config/`
| File | Purpose |
|------|---------|
| `persona.yaml` | Identity facts, style traits, never_do constraints, uncertainty phrases |
| `confidence_thresholds.yaml` | default 0.85, graduated_spaces map for per-room overrides |

### Test suite: `services/agent/tests/`
| File | Tests |
|------|-------|
| `test_classifier.py` | 31 tests — mode classification, intent, deadline risk |
| `test_confidence.py` | 17 tests — score modifiers, clipping, threshold lookup |
| `test_prompt_builder.py` | 18 tests — message structure, memory injection, style examples, user message content |
| `test_pipeline.py` | 12 tests — draft path, auto-send path, inward mode, error handling, memory calls |

### Dependencies installed
- `pyyaml` — config loading
- `pytest`, `pytest-asyncio` — test runner

## Tasks Completed
- [x] `config/persona.yaml`
- [x] `config/confidence_thresholds.yaml`
- [x] `services/agent/llm_client.py` — Claude API with structured output
- [x] `services/agent/classifier.py` — mode + intent + deadline risk
- [x] `services/agent/prompt_builder.py` — RAG + style examples injection
- [x] `services/agent/confidence.py` — scoring + per-room thresholds
- [x] `services/agent/draft_queue.py` — Postgres-backed queue
- [x] `services/agent/matrix_sender.py` — Matrix send + rate limit
- [x] `services/agent/pipeline.py` — full orchestration
- [x] `services/agent/prompts/outward_system.md`
- [x] `services/agent/prompts/inward_system.md`
- [x] Unit + integration tests (78 tests, all passing)
- [x] `import services.agent` verified clean

## Tests Status
- Type check: N/A (no mypy configured in project)
- Unit tests: **78/78 passed** in 1.16s
- Integration tests: pipeline tests use full mocked stack (LLM, memory, DB, Matrix)

## Design Decisions
- **No Redis event bus wiring yet** — phase spec says "wire to Redis event bus" but the bus consumer is Phase 4/6 scope; `AgentPipeline.process_event()` is the integration point, kept clean for caller to wire
- **`LLMClient` structured output**: appends JSON instruction to system prompt; falls back to plain text with confidence=0.3 on parse failure so reply always lands in draft queue, never silently dropped
- **`matrix_sender.py` is sync-in-executor** — mirrors the pattern from `scripts/matrix-listener.py` using stdlib `urllib` to avoid adding `httpx` dependency
- **`docker-compose.yml` not modified** — phase file lists it as "Modify" but the agent runs on host (per spec: "does NOT need to be containerized yet")

## Unresolved Questions
1. **Style examples source** — `config/style_examples.jsonl` not created; Khanh's sent messages are filtered out by the Matrix listener (skips own puppet). Options: (a) manual export, (b) modify listener to capture sent messages separately, (c) fetch via `/messages` API with full history. Pipeline accepts `style_examples` param in `PromptBuilder.build()` — ready when data is available.
2. **`event_id` FK in draft_replies** — pipeline passes `event.get("event_id")` which is the Matrix event ID string, not the episodic store UUID. If callers pass Matrix event IDs here the FK will fail. Current code only sets it when the value is a valid UUID string; callers should log to episodic first and pass the returned UUID.

**Status:** DONE_WITH_CONCERNS
**Summary:** Full dual-mode agent package implemented, 78 tests passing. Pipeline is wirable — `AgentPipeline.process_event(event)` is the public entry point.
**Concerns:** Style examples data source unresolved (see Q1 above). Redis event bus wiring deferred to Phase 4/6 as intended.
