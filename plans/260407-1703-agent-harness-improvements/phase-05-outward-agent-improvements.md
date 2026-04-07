# Phase 5: Outward Agent Improvements

## Overview
- **Priority:** P2
- **Status:** Complete
- **Effort:** 3h
- **Depends on:** Phase 1 (LLM router provides should_respond, priority), Phase 2 (ContextBundle)

Use LLM router output to drive outward behavior instead of hardcoded group chat rules and confidence modifiers.

## Key Insights
- Current group chat skip logic: `if is_group and not is_mentioned and intent in ("social", "humor", "greeting", "fyi")` — hardcoded in OutwardReplySkill line 62
- Confidence modifiers are hardcoded constants (e.g., `MODIFIER_GROUP_SOCIAL_SKIP = -0.90`) — should be configurable
- Thread-aware responses: if owner is participating in a thread, agent should always engage regardless of intent
- `_is_group_chat` is duplicated in `confidence.py:132` and `matrix_channel_adapter.py:151` — both use broken room-name heuristics

## Requirements

### Functional
1. Use `RouterResult.should_respond` as primary gate (replaces hardcoded skip logic)
2. Use `RouterResult.priority` to adjust confidence (high priority → boost, low → reduce)
3. Thread-aware: if owner has messages in thread, always respond (from router)
4. Move confidence modifiers to `config/confidence_thresholds.yaml` (not hardcoded)
5. Remove duplicate `_is_group_chat` methods — use `CanonicalMessage.is_group` everywhere

## Architecture

```
RouterResult
  │
  ├── should_respond = False → skip (no LLM call, no draft)
  │
  ├── should_respond = True
  │     │
  │     ├── priority = "high"   → confidence += config.high_priority_boost
  │     ├── priority = "medium" → no modifier
  │     └── priority = "low"    → confidence += config.low_priority_penalty
  │
  └── ContextBundle → PromptBuilder → AgentLoop → ConfidenceScorer → route
```

### Config-driven Modifiers
```yaml
# config/confidence_thresholds.yaml (additions)
modifiers:
  many_memories: 0.10
  deadline_risk: -0.20
  unknown_sender: -0.15
  social_dm: 0.25
  no_history: -0.90
  cautious_sender: -0.30
  high_priority_boost: 0.15
  low_priority_penalty: -0.10
```

## Related Code Files

### Modify
- `services/agent/skills/outward_reply_skill.py` — Remove hardcoded skip logic, use RouterResult
- `services/agent/confidence.py` — Load modifiers from config, remove `_is_group_chat`, remove duplicate logic
- `config/confidence_thresholds.yaml` — Add modifiers section

### Delete (dead code after refactor)
- `services/agent/confidence.py` → `_is_group_chat` method
- `services/agent/matrix_channel_adapter.py` → `_detect_group_chat` function (replaced by member_count in Phase 1)

## Implementation Steps

1. **Move confidence modifiers to config**
   - Add `modifiers:` section to `config/confidence_thresholds.yaml`
   - Update `ConfidenceScorer.__init__` to load modifiers from config
   - Replace hardcoded constants (`MODIFIER_*`) with config values
   - Keep constants as defaults (backward compat if config missing)

2. **Use RouterResult in OutwardReplySkill**
   - Pass `RouterResult` through `SkillContext`
   - Replace lines 60-70 (hardcoded group skip) with: `if not router_result.should_respond: return skipped`
   - Use `router_result.priority` to adjust confidence scoring

3. **Add priority-based confidence modifiers**
   - In `ConfidenceScorer.score()`: accept optional `priority` param
   - Apply `high_priority_boost` or `low_priority_penalty` from config
   - High priority (mentioned, direct question) → more likely to auto-send

4. **Remove duplicate group detection**
   - Delete `_is_group_chat` from `confidence.py`
   - Delete `_detect_group_chat` from `matrix_channel_adapter.py`
   - Both replaced by `CanonicalMessage.is_group` (set from member_count in Phase 1)
   - Update `ConfidenceScorer.score()` to accept `is_group` param instead of calling `_is_group_chat(event)`

5. **Thread-aware response in OutwardReplySkill**
   - RouterResult already carries `should_respond=True` for threads where owner participates
   - OutwardReplySkill trusts router — no additional thread logic needed in skill
   - Remove `_is_mentioned` static method — router handles this

## Todo

- [x] Move confidence modifier constants to config YAML
- [x] Update ConfidenceScorer to load modifiers from config
- [x] Add RouterResult to SkillContext
- [x] Replace hardcoded skip logic with RouterResult.should_respond
- [x] Add priority-based confidence adjustment
- [x] Remove duplicate _is_group_chat / _detect_group_chat
- [x] Remove _is_mentioned from OutwardReplySkill (router handles it)
- [x] Unit tests for config-driven modifiers
- [x] Integration test: thread participation → always respond

## Success Criteria
- Zero hardcoded confidence modifiers in Python code (all in YAML config)
- Group chat detection uses member_count (100% accurate vs ~70% heuristic)
- Thread participation → always responds (verified with test)
- Changing a modifier requires editing YAML only (no code deploy)
- No duplicate group detection logic anywhere in codebase

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Config YAML syntax error breaks scoring | Low | High | Validate on load, fall back to defaults |
| Router should_respond too aggressive (skips important messages) | Medium | High | Log all skip decisions, review daily for false negatives |
| Thread detection false positive (responds to unrelated threads) | Low | Medium | Router reasoning logged, can tune prompt |
| Removing _is_mentioned breaks mention detection | Low | Medium | Router handles mentions; if router fails, regex fallback in Phase 1 still runs |
