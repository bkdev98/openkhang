# Phase 3: Unified Agent Loop

## Overview
- **Priority:** P1
- **Status:** Complete
- **Effort:** 4h
- **Depends on:** Phase 2 (ContextBundle feeds into the loop)

Merge the outward deterministic path and inward ReAct loop into a single execution flow. Mode differences handled by config (prompt, temperature, tool access, output format) — not separate code paths.

## Key Insights
- Current state: outward = `LLM(structured JSON) → parse → score → route`, inward = `ReAct loop (3 iters, 30s) → text`
- Outward mode MUST stay deterministic for safety (no tool_use that auto-sends) — this is a config constraint, not a code path
- Inward loop is capped at 3 iterations/30s — too restrictive for complex queries
- Hacky `[System:]` message in `inward_query_skill.py:83-91` forces tool use — should be in system prompt
- Extended thinking would help inward mode reason about complex multi-step queries

## Requirements

### Functional
1. Single `AgentLoop` class that handles both modes
2. Mode config controls: system prompt, temperature, tool whitelist, output format, max iterations, timeout
3. Outward config: structured output, 0.3 temp, no tools, max_iter=1, 60s timeout
4. Inward config: free-form output, 0.5 temp, all safe tools, max_iter=10, 120s timeout
5. Remove `[System:]` hack — move tool-use instruction to system prompt
6. Support extended thinking for inward mode (when available via Meridian)

### Non-Functional
- No behavior change for outward mode (same structured JSON flow)
- Inward mode gets more room to reason (10 iters, 120s)

## Architecture

```
ContextBundle + RouterResult
       │
       ▼
AgentLoop.run(mode_config, context_bundle, event)
       │
       ├── mode_config.use_tools = False  → single LLM call (outward)
       │     └── structured output → parse → score → route
       │
       └── mode_config.use_tools = True   → ReAct loop (inward)
             └── up to 10 iterations, 120s timeout
             └── tool whitelist from mode_config
```

### Mode Config
```python
@dataclass
class ModeConfig:
    system_prompt_file: str       # "outward_system.md" | "inward_system.md"
    temperature: float            # 0.3 outward, 0.5 inward
    max_tokens: int               # 4096
    use_tools: bool               # False outward, True inward
    tool_whitelist: set[str]      # empty = all, or specific names
    tool_blacklist: set[str]      # {"create_draft", "send_message"} for inward
    require_structured: bool      # True outward, False inward
    max_iterations: int           # 1 outward, 10 inward
    timeout_seconds: int          # 60 outward, 120 inward
    enable_extended_thinking: bool  # False outward, True inward (when supported)
```

## Related Code Files

### Modify
- `services/agent/tool_calling_loop.py` — Increase defaults, accept ModeConfig
- `services/agent/skills/outward_reply_skill.py` — Delegate to AgentLoop instead of direct LLM call
- `services/agent/skills/inward_query_skill.py` — Delegate to AgentLoop, remove [System:] hack
- `services/agent/pipeline.py` — Initialize AgentLoop, pass ModeConfig

### Create
- `services/agent/agent_loop.py` — Unified AgentLoop class

### Keep Unchanged
- `services/agent/llm_client.py` — Already supports both generate() and generate_with_tools()
- `services/agent/tool_registry.py` — No changes needed

## Implementation Steps

1. **Define ModeConfig dataclass** in `agent_loop.py`
   - Outward preset: `ModeConfig.outward()` class method
   - Inward preset: `ModeConfig.inward()` class method
   - Load from YAML config later (hot-reload friendly)

2. **Implement AgentLoop**
   - `async def run(mode_config, messages, tools, llm_client) -> AgentLoopResult`
   - If `use_tools=False`: single LLM call via `llm.generate()` (outward path)
   - If `use_tools=True`: call existing `run_tool_calling_loop()` with config params
   - Apply tool whitelist/blacklist filtering before passing tools
   - Timeout enforcement via `asyncio.wait_for()`

3. **Update tool_calling_loop.py**
   - Change defaults: `MAX_ITERATIONS = 10`, `LOOP_TIMEOUT_SECONDS = 120`
   - Accept these as params (already does via function args)
   - No structural changes — AgentLoop wraps it

4. **Remove [System:] hack from InwardQuerySkill**
   - Delete lines 82-91 in `inward_query_skill.py`
   - Add tool-use instruction to `inward_system.md` prompt (Phase 4 will refine further)

5. **Refactor skills to use AgentLoop**
   - OutwardReplySkill: replace `llm.generate(require_structured=True)` with `AgentLoop.run(ModeConfig.outward())`
   - InwardQuerySkill: replace `run_tool_calling_loop()` with `AgentLoop.run(ModeConfig.inward())`
   - Both skills become thin: context → prompt → loop → route

6. **Extended thinking support** (optional, gated)
   - Add `enable_extended_thinking` flag to ModeConfig
   - If supported by Meridian, pass `thinking` parameter to LLM call
   - No-op if Meridian doesn't support it yet

## Todo

- [x] Define ModeConfig dataclass with outward/inward presets
- [x] Implement AgentLoop.run()
- [x] Update tool_calling_loop defaults (10 iters, 120s)
- [x] Remove [System:] hack from InwardQuerySkill
- [x] Refactor OutwardReplySkill to use AgentLoop
- [x] Refactor InwardQuerySkill to use AgentLoop
- [x] Add tool whitelist/blacklist filtering
- [x] Add extended thinking support (gated)
- [x] Unit tests for AgentLoop (both modes)
- [x] Integration test: outward mode still produces structured JSON

## Success Criteria
- Single code path for LLM execution (AgentLoop) — no mode-specific LLM calling code in skills
- Inward mode can handle 10-iteration queries without timeout
- Outward mode behavior is byte-identical to current (structured JSON, same confidence scoring)
- [System:] hack removed, tool instruction lives in system prompt
- Adding a new mode = adding a ModeConfig preset (no new skill code)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Outward behavior changes | Medium | High | Regression test: compare outputs on 20 real messages before/after |
| 10-iteration inward loops burn tokens | Low | Medium | Token budget cap in ModeConfig, monitor via trace |
| Extended thinking not supported by Meridian | High | Low | Feature-gated, graceful no-op |
| Removing [System:] hack reduces tool usage | Medium | Medium | Move instruction to system prompt immediately (not wait for Phase 4) |
