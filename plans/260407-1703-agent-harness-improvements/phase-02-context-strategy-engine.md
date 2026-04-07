# Phase 2: Context Strategy Engine

## Overview
- **Priority:** P1
- **Status:** Complete
- **Effort:** 3h
- **Depends on:** Phase 1 (router provides intent + priority)

Replace ad-hoc context gathering scattered across skills with a centralized context strategy that fetches the right data for each intent in parallel.

## Key Insights
- `OutwardReplySkill` gathers: RAG + code search + sender context + room history + thread messages (sequential, ~4 async calls)
- `InwardQuerySkill` gathers: sender context only (lets agent fetch via tools — but agent often doesn't)
- Context is fetched sequentially in outward — parallelizing saves 30-50% latency
- Some context is unnecessary: social intent fetches RAG (already skipped via `skip_rag` flag, but logic is inline and duplicated)
- Agent tools exist for fetching context but inward prompt doesn't teach the agent WHEN to use them

### Patterns from OpenClaw + Claude Code
- **OpenClaw AGENTS.md:** "Read these files first: SOUL.md, USER.md, memory/today.md. Don't ask permission. Just do it." — proactive context, not reactive
- **Claude Code:** Injects git status, recent commits, file modifications into system context automatically before agent starts thinking
- **Key insight:** Pre-inject context into the prompt so the agent starts with knowledge, not with a blank slate that requires tool calls to fill

## Requirements

### Functional
1. Define context requirements per intent (declarative config, not code)
2. Pre-fetch required context in parallel using `asyncio.gather`
3. Return a `ContextBundle` dataclass with all fetched data
4. Skills receive `ContextBundle` instead of fetching context themselves
5. Agent still has tools to fetch additional context beyond pre-fetched set

### Non-Functional
- Parallel fetch must not increase total latency vs current sequential
- Must handle partial failures gracefully (one fetch fails, rest succeed)

## Architecture

```
RouterResult (intent, priority)
      │
      ▼
ContextStrategy.resolve(intent, event)
      │
      ├── intent="social"   → {} (no context needed)
      ├── intent="fyi"      → {sender_context}
      ├── intent="question"  → {rag, code_search, sender_context, room_messages}
      ├── intent="request"   → {rag, sender_context, room_messages, thread_messages}
      └── intent="query"     → {rag, code_search} (inward)
      │
      ▼ (asyncio.gather — parallel)
ContextBundle(memories, code_results, sender_context, room_messages, thread_messages)
```

### Context Strategy Config
```python
CONTEXT_STRATEGIES: dict[str, list[str]] = {
    "social":      [],
    "fyi":         ["sender"],
    "question":    ["rag", "code", "sender", "room"],
    "request":     ["rag", "sender", "room", "thread"],
    "instruction": ["rag", "sender"],
    "query":       ["rag", "code"],
}
```

## Related Code Files

### Modify
- `services/agent/skills/outward_reply_skill.py` — Remove inline context gathering, receive ContextBundle
- `services/agent/skills/inward_query_skill.py` — Remove inline sender context fetch, receive ContextBundle
- `services/agent/pipeline.py` — Add context strategy step between routing and skill dispatch
- `services/agent/skill_registry.py` — Add `context` field to SkillContext

### Create
- `services/agent/context_strategy.py` — ContextStrategy class + ContextBundle dataclass

## Implementation Steps

1. **Define ContextBundle dataclass**
   ```python
   @dataclass
   class ContextBundle:
       memories: list[dict]          # RAG results
       code_results: list[dict]      # Code search results
       sender_context: list[dict]    # Prior interactions with sender
       room_messages: list[dict]     # Recent room/thread messages
       thread_messages: list[dict]   # Thread-specific messages
   ```

2. **Implement ContextStrategy**
   - `CONTEXT_STRATEGIES` dict mapping intent → list of fetch keys
   - `async def resolve(intent, event, memory_client) -> ContextBundle`
   - Each fetch key maps to an async fetcher function
   - Use `asyncio.gather(*fetchers, return_exceptions=True)` for parallel execution
   - Log and skip failed fetchers (partial success is fine)

3. **Wire into pipeline**
   - After router returns `RouterResult`, call `ContextStrategy.resolve(intent, event)`
   - Pass `ContextBundle` into `SkillContext`
   - Skills read from `context.bundle` instead of calling memory client directly

4. **Refactor OutwardReplySkill**
   - Remove lines 74-124 (inline RAG, code search, sender context, room messages)
   - Read all context from `context.bundle`
   - Keep confidence scoring and routing logic unchanged

5. **Refactor InwardQuerySkill**
   - Remove lines 64-72 (inline sender context fetch)
   - Read sender context from `context.bundle`
   - Keep tool-calling loop unchanged (agent can still fetch more via tools)

6. **Update PromptBuilder**
   - Accept `ContextBundle` instead of individual memory/sender/room params
   - Simplify `build()` signature

## Todo

- [x] Create ContextBundle dataclass
- [x] Implement ContextStrategy with parallel fetching
- [x] Define strategy config per intent
- [x] Wire context strategy into pipeline
- [x] Refactor OutwardReplySkill to use ContextBundle
- [x] Refactor InwardQuerySkill to use ContextBundle
- [x] Update PromptBuilder to accept ContextBundle
- [x] Handle partial fetch failures gracefully
- [x] Unit tests for ContextStrategy (mock memory client)

## Success Criteria
- Outward reply latency reduced by 20-30% via parallel fetching
- Social messages skip all context fetching (0 memory client calls)
- Adding a new intent requires only adding an entry to `CONTEXT_STRATEGIES` dict
- All existing tests still pass (behavior unchanged)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Parallel fetch causes memory spikes | Low | Low | Limit concurrency, same data volume as sequential |
| PromptBuilder signature change breaks callers | Medium | Medium | Add backward-compat overload, deprecate old signature |
| Missing context for edge-case intents | Low | Medium | Default strategy fetches rag+sender (safe baseline) |
