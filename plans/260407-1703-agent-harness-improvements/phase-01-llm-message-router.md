# Phase 1: LLM-based Message Router

## Overview
- **Priority:** P1
- **Status:** Complete
- **Effort:** 4h

Replace regex-based `Classifier` with a cheap LLM call (haiku-class) that evaluates message context holistically. Keep regex as fast-path for trivial social greetings (no LLM call needed).

## Key Insights
- Current `_detect_group_chat()` uses room name heuristics (`" " in room_name or "-" in room_name`) — misclassifies Vietnamese names with spaces as groups
- Intent classification is regex + order-dependent — "can you review" matches REQUEST before QUESTION even if it's a question
- No thread awareness — agent can't distinguish "active thread participant" from "random group noise"
- `CanonicalMessage` already carries `is_group` and `is_mentioned` but they're set by same broken heuristics

## Requirements

### Functional
1. LLM router receives: message body, room metadata (is_group from member count, room type), thread context (is user in this thread?), sender info
2. LLM router returns: `{ mode, intent, should_respond, priority, reasoning }`
3. Social greetings bypass LLM (regex fast-path stays for `SOCIAL_PATTERNS`)
4. Router uses haiku-class model via Meridian (cheap, fast — target <500ms)
5. Fallback to regex if LLM router fails (network, timeout)

### Non-Functional
- Router call must complete in <1s (p95)
- Must not block pipeline startup

## Architecture

```
event
  │
  ├─ regex fast-path ──→ social? → skip LLM, return {mode, intent:"social", should_respond}
  │
  └─ LLM router call ──→ haiku model with structured output
       │                    Input: body, room_meta, thread_meta, sender_meta
       │                    Output: {mode, intent, should_respond, priority, reasoning}
       │
       └─ fallback ──→ regex classifier (current code, unchanged)
```

### Room Metadata (fix group detection)
- Use `CanonicalMessage.raw` to access mautrix room state: member count, room type (dm vs group), joined members list
- `is_group = member_count > 2` (from Matrix room state) instead of room name heuristics
- Thread relevance: check if owner's Matrix user ID appears in thread participants

## Related Code Files

### Modify
- `services/agent/classifier.py` — Add `LLMRouter` class, keep `Classifier` as fallback
- `services/agent/pipeline.py` — Wire LLM router before skill dispatch
- `services/agent/matrix_channel_adapter.py` — Pass room member count in CanonicalMessage, fix `_detect_group_chat`
- `services/agent/channel_adapter.py` — Add `member_count`, `room_type` fields to CanonicalMessage

### Create
- `services/agent/llm_router.py` — LLM-based message router (new module, <150 lines)
- `services/agent/prompts/router_prompt.md` — Router system prompt

## Implementation Steps

1. **Add room metadata to CanonicalMessage**
   - Add `member_count: int = 0` and `room_type: str = ""` fields
   - Update `to_legacy_dict()` to include new fields
   - Update `MatrixChannelAdapter.normalize_inbound()` to extract member count from Matrix room state (mautrix API)

2. **Create router prompt** (`prompts/router_prompt.md`)
   - Concise system prompt for haiku: "You are a message router. Classify this message..."
   - Define structured output schema in prompt
   - Include examples for edge cases (Vietnamese names, thread mentions)

3. **Implement `LLMRouter`** (`llm_router.py`)
   - `async def route(event: dict, llm_client: LLMClient) -> RouterResult`
   - Uses haiku model via Meridian (`model="claude-haiku-3"` or cheapest available)
   - Parses structured JSON output
   - Returns `RouterResult(mode, intent, should_respond, priority, reasoning)`
   - On failure: log warning, return `None` (caller falls back to regex)

4. **Wire into pipeline**
   - In `pipeline.process_event()`: call `LLMRouter.route()` first
   - If returns `RouterResult` with `should_respond=False`: return early (skipped)
   - If returns `None` (failure): fall back to `Classifier.classify_mode/intent`
   - Pass `RouterResult` to skill context so skills can use priority/reasoning

5. **Fix group detection**
   - Replace `_detect_group_chat(room_name)` with `member_count > 2`
   - Remove duplicate `_is_group_chat` in `confidence.py` — use CanonicalMessage.is_group
   - Keep room-name heuristic ONLY as fallback when member_count unavailable

6. **Add thread awareness**
   - In router prompt: include thread participant list
   - Rule: if owner is active in thread, `should_respond=True` regardless of intent
   - Requires passing thread_participants from Matrix adapter

## Todo

- [x] Add member_count/room_type to CanonicalMessage
- [x] Extract room member count in MatrixChannelAdapter
- [x] Write router system prompt
- [x] Implement LLMRouter class
- [x] Wire LLM router into pipeline.process_event()
- [x] Fix group detection (member_count > 2)
- [x] Add thread participant awareness
- [x] Add regex fast-path bypass for social patterns
- [x] Fallback to regex Classifier on LLM failure
- [x] Unit tests for LLMRouter (mock LLM responses)

## Success Criteria
- Group chat detection accuracy: 100% for rooms with known member count (vs current ~70% heuristic)
- Intent classification handles ambiguous messages (e.g., "can you check this?" = request, not question)
- Router adds <800ms p95 latency for non-social messages
- Social messages incur 0ms router overhead (regex fast-path)
- Regex fallback works seamlessly when LLM is unavailable

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Haiku latency too high (>1s) | Medium | Medium | Use smallest model, cache prompt, set 2s timeout |
| LLM router misclassifies | Medium | Medium | Regex fallback always available, log router reasoning for tuning |
| Matrix room state unavailable | Low | Low | Fall back to room-name heuristic (current behavior) |
| Meridian down during routing | Low | High | Regex fallback path, circuit breaker pattern |

## Security
- Router prompt must not leak system internals in reasoning field
- Do not pass full message body to router if it contains PII — truncate to first 200 chars
