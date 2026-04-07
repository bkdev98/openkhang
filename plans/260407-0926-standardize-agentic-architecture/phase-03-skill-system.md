# Phase 3: Skill System

## Context Links
- [Plan overview](plan.md)
- [Phase 2 — Tool Registry](phase-02-tool-registry-and-conversion.md) (blocker)
- [Agent skills ecosystem](../reports/researcher-260407-0854-agent-skills-ecosystem.md) — SKILL.md format, progressive disclosure
- [OpenClaw skill-on-demand](../reports/researcher-260407-0854-openclaw-architecture.md) — compact reference + lazy load

## Overview
- **Priority:** P2
- **Effort:** 1.5 days
- **Status:** Pending
- **Blockers:** Phase 2 (skills orchestrate tools)

Extract pipeline logic into composable skills. Skills are markdown instruction files + optional Python scripts that orchestrate tools. A `SkillRegistry` manages discovery, matching, and loading with progressive disclosure (~100 tokens per skill description upfront; full instructions loaded on demand).

## Key Insights
- Skills ≠ tools. Tools execute single actions; skills encode multi-step workflows with judgment calls.
- Current `pipeline.process_event()` (520 LOC) is effectively two hardcoded skills: outward_reply and inward_query. `twin_chat._execute_send_action()` is a third (send_as_khanh). Code search scattered across pipeline is a fourth.
- Progressive disclosure matters: 4 skills x ~100 tokens = 400 tokens upfront vs 4 x ~2000 tokens = 8000 if all loaded. At scale with 10+ skills, this saves real context window.
- Skill activation: for this project, use **deterministic matching** (mode + intent → skill), not probabilistic LLM matching (research shows ~20% success rate for description-based matching).

## Requirements

### Functional
- F1: `SkillRegistry` with `register()`, `match(mode, intent)`, `load_skill()`, `list_summaries()`
- F2: `BaseSkill` ABC with `name`, `description` (~100 tokens), `match_criteria`, `execute(msg, tools, context)`
- F3: Extract 4 skills from existing code:
  - `outward-reply` — full outward pipeline (classify → RAG → style → confidence → route)
  - `inward-query` — full inward pipeline (RAG → prompt → LLM → return)
  - `send-as-khanh` — from twin_chat (lookup person → compose → send)
  - `code-search` — standalone code search workflow
- F4: Skills call tools from Phase 2 registry (not direct method calls)
- F5: `pipeline.process_event()` delegates to matched skill instead of inline logic
- F6: Each skill is a Python class, optionally paired with a SKILL.md instruction file

### Non-Functional
- NF1: All 78 tests pass (skills replicate exact existing behavior)
- NF2: Adding a new skill requires only: create class + register — zero pipeline changes
- NF3: Each skill file <150 LOC

## Architecture

### Skill Matching (Deterministic)
```
CanonicalMessage → (mode, intent) → SkillRegistry.match() → matched Skill → skill.execute()
```

Match rules (hardcoded, not LLM-based):
| Mode | Intent | Skill |
|------|--------|-------|
| outward | * | outward-reply |
| inward | instruction (send pattern detected) | send-as-khanh |
| inward | query/question (code keywords detected) | code-search (then falls through to inward-query) |
| inward | * | inward-query |

### Skill Execute Signature
```python
class BaseSkill(ABC):
    @abstractmethod
    async def execute(
        self,
        msg: CanonicalMessage,
        tools: ToolRegistry,
        llm: LLMClient,
        context: SkillContext,
    ) -> AgentResult:
        ...

@dataclass
class SkillContext:
    """Injected context available to all skills."""
    classifier: Classifier
    scorer: ConfidenceScorer
    prompt_builder: PromptBuilder
    style_examples: list[dict]
    chat_history: list[dict] | None = None
```

### Data Flow (After)
```
agent_relay → adapter.normalize() → CanonicalMessage
                    ↓
    pipeline.process_event(msg)
                    ↓
    skill = registry.match(mode, intent)
    result = await skill.execute(msg, tools, llm, context)
                    ↓
    router.dispatch(result, msg)  # Phase 1
                    ↓
    log_event(result)
```

### Progressive Disclosure
```python
# At pipeline init: load only summaries (~400 tokens total)
for skill in registry.list_summaries():
    # {name: "outward-reply", description: "Reply as Khanh in Google Chat...", match: {...}}

# On match: full skill instructions loaded (SKILL.md read from disk)
skill = registry.load_skill("outward-reply")
# skill.instructions → full markdown loaded on demand
```

## Related Code Files

### Files to Create
| File | Purpose | Lines (est) |
|------|---------|-------------|
| `services/agent/skill-registry.py` | BaseSkill ABC + SkillRegistry + SkillContext | ~90 |
| `services/agent/skills/outward-reply-skill.py` | Outward pipeline extracted from pipeline.py | ~140 |
| `services/agent/skills/inward-query-skill.py` | Inward pipeline extracted from pipeline.py | ~80 |
| `services/agent/skills/send-as-khanh-skill.py` | Send action extracted from twin_chat.py | ~100 |
| `services/agent/skills/code-search-skill.py` | Code search workflow (can compose with inward-query) | ~80 |
| `services/agent/skills/__init__.py` | Re-exports all skills | ~10 |

### Files to Modify
| File | Change |
|------|--------|
| `services/agent/pipeline.py` | Replace inline logic in process_event() with skill matching + delegation. Shrinks from ~520 to ~150 LOC. |
| `services/dashboard/twin_chat.py` | Remove `_execute_send_action()` logic (moved to send-as-khanh skill). ask_twin() becomes thin: normalize → pipeline → return. |

### Files NOT Modified
| File | Reason |
|------|--------|
| `services/agent/classifier.py` | Used by skills via SkillContext — unchanged |
| `services/agent/confidence.py` | Used by outward-reply skill via SkillContext — unchanged |
| `services/agent/prompt_builder.py` | Used by skills via SkillContext — unchanged |
| `services/agent/llm_client.py` | Passed to skills — unchanged |
| All tool files (Phase 2) | Skills call tools; tools don't know about skills |

## Implementation Steps

1. **Create `services/agent/skill-registry.py`**
   - `BaseSkill` ABC: name, description, match_criteria (dict with mode/intent patterns), execute()
   - `SkillContext` dataclass holding shared pipeline components
   - `SkillRegistry`: register(), match(mode, intent) → BaseSkill, list_summaries()
   - match() logic: iterate registered skills, check match_criteria against mode + intent + body patterns

2. **Create `services/agent/skills/outward-reply-skill.py`**
   - Extract from pipeline.py lines 149-300 (Steps 1-7 of process_event for outward mode)
   - execute() calls tools: search_knowledge, search_code, get_sender_context, get_room_history
   - Then: prompt_builder.build() → llm.generate() → scorer.score() → route via create_draft or send_message tool
   - Match criteria: `{"mode": "outward"}`

3. **Create `services/agent/skills/inward-query-skill.py`**
   - Extract from pipeline.py inward path
   - execute() calls tools: search_knowledge, search_code, get_sender_context
   - Then: prompt_builder.build() → llm.generate() → return AgentResult(action="inward_response")
   - Match criteria: `{"mode": "inward"}`

4. **Create `services/agent/skills/send-as-khanh-skill.py`**
   - Extract from twin_chat.py `_execute_send_action()` + `_enrich_with_context()`
   - execute() calls tools: lookup_person, get_room_history → compose message → send_message
   - Match criteria: `{"mode": "inward", "body_pattern": "send|say|tell|nhắn|gửi"}`
   - Higher priority than inward-query (matched first)

5. **Create `services/agent/skills/code-search-skill.py`**
   - Standalone code search: calls search_code tool → formats results → returns
   - Can be composed: if result needs synthesis, delegates to inward-query skill
   - Match criteria: `{"mode": "inward", "intent": "query", "body_pattern": "code|search code|tìm code"}`

6. **Refactor `services/agent/pipeline.py`**
   - Move all inline processing logic into skills
   - process_event() becomes:
     ```
     classify → match skill → skill.execute() → log_event → return result
     ```
   - Keep backward-compat: if no skill matches, fall back to inline logic (safety net during transition)
   - Target: pipeline.py shrinks from ~520 to ~150 LOC

7. **Refactor `services/dashboard/twin_chat.py`**
   - Remove `_execute_send_action()`, `_enrich_with_context()`, `_extract_composed_message()`
   - `ask_twin()` becomes: normalize → pipeline.process_event() → return
   - Action detection moved to skill matching (send-as-khanh skill's match_criteria)

8. **Write skill unit tests**
   - Test each skill's execute() with mocked tools + LLM
   - Test SkillRegistry matching logic
   - Test that outward-reply produces identical AgentResult to current pipeline

9. **Run all tests** — 78 existing + new skill tests pass

## Todo Checklist

- [ ] Create `BaseSkill` ABC + `SkillRegistry` + `SkillContext`
- [ ] Create `outward-reply-skill.py`
- [ ] Create `inward-query-skill.py`
- [ ] Create `send-as-khanh-skill.py`
- [ ] Create `code-search-skill.py`
- [ ] Refactor `pipeline.py` to delegate to skills
- [ ] Refactor `twin_chat.py` to remove extracted logic
- [ ] Write unit tests for each skill
- [ ] Write unit tests for SkillRegistry matching
- [ ] Verify outward-reply produces identical results to current pipeline
- [ ] All 78 existing tests pass
- [ ] pipeline.py is under 200 LOC

## Success Criteria
- All 78 existing tests pass
- `pipeline.py` shrinks from ~520 to <200 LOC
- `twin_chat.py` shrinks (action logic moved to skill)
- Adding a new skill: 1 file + 1 register() call — zero pipeline changes
- Outward mode behavior byte-identical to pre-refactor (confidence scores, draft vs auto-send decisions)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Outward skill misses edge case from pipeline | Medium | High | Diff test: run both paths (inline + skill) in parallel, assert identical AgentResult for 20 test events |
| Skill matching ambiguity (send_as_khanh vs inward_query) | Medium | Medium | Priority ordering: send-as-khanh checked first; explicit body_pattern match required |
| SkillContext becomes god object | Low | Medium | SkillContext is read-only dataclass; skills can't mutate shared state |
| twin_chat refactor breaks dashboard | Medium | Medium | Incremental: keep old code behind flag, test new path, then remove old |

## Security Considerations
- Skills must not bypass confidence scoring for outward mode (outward-reply skill must always run scorer)
- send-as-khanh skill must only send to DM rooms (never groups) — preserves existing room_lookup constraint
- Skill descriptions (for future LLM matching) must not contain persona secrets or API keys

## Next Steps
- Phase 4 can use SkillRegistry to decide which tools to expose to Claude tool_use per skill
- Future: SKILL.md files alongside Python skills for LLM-readable instructions
- Future: skill marketplace pattern for sharing skills across projects
