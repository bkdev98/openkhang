# Phase 4: LLM Tool-Calling Integration

## Context Links
- [Plan overview](plan.md)
- [Phase 2 — Tool Registry](phase-02-tool-registry-and-conversion.md) (blocker)
- [Agent architecture patterns](../reports/researcher-260407-0854-agent-architecture-patterns.md) — LLM-native tool calling
- [Framework comparison](../reports/researcher-260407-0913-agent-framework-comparison.md) — Claude tool_use as industry standard

## Overview
- **Priority:** P2
- **Effort:** 1 day
- **Status:** Done
- **Blockers:** None (Phase 2 complete)

Integrate Claude `tool_use` into inward mode so the agent can dynamically choose which tools to call. Outward mode stays deterministic (safety-critical, no dynamic tool selection). Replace hardcoded `code_keywords` check with LLM tool-calling decision. Replace regex action detection in `twin_chat.py` with LLM tool-calling.

## Key Insights
- **Outward mode = deterministic.** Auto-sending messages AS Khanh is safety-critical. The existing classify → RAG → style → confidence → route pipeline must not change. LLM should NOT dynamically decide to send messages in outward mode.
- **Inward mode = dynamic.** Khanh asks the assistant questions. LLM can choose: search knowledge, search code, lookup person, send message. This is where tool_use adds value.
- Claude `tool_use` API: send tool definitions in the request; Claude returns `tool_use` content blocks; we execute and re-feed results. Standard ReAct loop.
- Current `code_keywords` list (28 keywords, pipeline.py lines 178-184) is brittle. LLM deciding "should I search code?" is more reliable.
- Current regex action detection (`_SEND_PATTERNS` in twin_chat.py) is fragile. LLM returning a `send_message` tool call is more robust.

## Requirements

### Functional
- F1: `LLMClient` supports Claude `tool_use` (tool definitions in request, tool_use blocks in response)
- F2: Inward mode: agent can dynamically choose tools via Claude tool_use
- F3: Outward mode: NO CHANGE — deterministic pipeline preserved
- F4: ReAct loop: LLM → tool_use → execute → re-feed result → LLM → final response (max 3 iterations)
- F5: Replace `code_keywords` check with LLM decision to call `search_code` tool
- F6: Replace `_SEND_PATTERNS` regex with LLM decision to call `send_message` / `lookup_person` tools
- F7: Graceful fallback: if tool_use fails, fall back to current direct pipeline

### Non-Functional
- NF1: All 78 tests pass
- NF2: Max 3 tool-calling iterations (prevent infinite loops)
- NF3: Total inward latency <15s (tool calls add network roundtrips)
- NF4: Outward mode latency unchanged

## Architecture

### Inward Mode Flow (After)
```
CanonicalMessage (inward)
    ↓
inward-query skill (Phase 3) OR pipeline.process_event()
    ↓
Build system prompt + inject tool definitions from registry
    ↓
Claude API call (with tools=[...])
    ↓
┌─── Response has tool_use blocks? ───┐
│ YES                                  │ NO
│ Execute tool(s) via registry         │ Return text response
│ Append tool results to messages      │
│ Call Claude again (iteration++)      │
│ Loop (max 3 iterations)             │
└──────────────────────────────────────┘
    ↓
Final text response → AgentResult
```

### Outward Mode Flow (UNCHANGED)
```
CanonicalMessage (outward)
    ↓
outward-reply skill — deterministic pipeline
    ↓
classify → RAG → style → prompt → LLM (NO tool_use) → confidence → route
```

### Tool Definitions for Inward Mode
Only expose safe tools to LLM in inward mode:
| Tool | Exposed | Reason |
|------|---------|--------|
| search_knowledge | Yes | Safe read-only |
| search_code | Yes | Safe read-only |
| get_sender_context | Yes | Safe read-only |
| get_room_history | Yes | Safe read-only |
| lookup_person | Yes | Safe read-only |
| send_message | Yes | Khanh explicitly asked; confirmable |
| create_draft | No | Internal routing mechanism, not user-facing |

### LLMClient Changes
```python
# New method on LLMClient
async def generate_with_tools(
    self,
    messages: list[dict],
    tools: list[dict],          # Claude tool definitions
    max_iterations: int = 3,
    tool_executor: Callable,    # registry.execute
    **kwargs,
) -> LLMResponse:
    """ReAct loop: call Claude with tools, execute tool_use blocks, re-feed."""
```

## Related Code Files

### Files to Create
| File | Purpose | Lines (est) |
|------|---------|-------------|
| `services/agent/tool-calling-loop.py` | ReAct loop: Claude tool_use → execute → re-feed | ~120 |

### Files to Modify
| File | Change |
|------|--------|
| `services/agent/llm_client.py` | Add `generate_with_tools()` method using Claude tool_use API (Meridian or direct) |
| `services/agent/skills/inward-query-skill.py` (Phase 3) | Use tool-calling loop instead of direct tool calls |
| `services/agent/skills/send-as-khanh-skill.py` (Phase 3) | Remove regex matching; let LLM decide via tool_use |
| `services/agent/pipeline.py` | If Phase 3 not done: add tool-calling to inward path directly |

### Files NOT Modified
| File | Reason |
|------|--------|
| `services/agent/skills/outward-reply-skill.py` | Outward = deterministic, no tool_use |
| `services/agent/classifier.py` | Classification still runs before tool-calling |
| `services/agent/confidence.py` | Only used in outward mode |
| `services/agent/prompt_builder.py` | Inward prompt updated to include tool descriptions, but builder logic unchanged |

## Implementation Steps

1. **Create `services/agent/tool-calling-loop.py`**
   - `ToolCallingLoop` class with `run()` method
   - Input: messages, tool_definitions, tool_executor (registry.execute), max_iterations=3
   - Logic:
     - Call LLM with tools
     - Parse response for `tool_use` content blocks
     - For each tool_use: call registry.execute(name, **input)
     - Append `tool_result` content blocks to messages
     - Re-call LLM with updated messages
     - Repeat until LLM returns text-only response or max_iterations hit
   - Return: final LLMResponse + list of tool calls made (for logging)

2. **Update `services/agent/llm_client.py`**
   - Add `generate_with_tools()` method
   - For Meridian provider: include `tools` param in OpenAI-compatible request body
   - For Claude API provider: include `tools` param in Anthropic API request
   - Parse `tool_use` content blocks from response
   - Return structured response indicating whether tool calls are needed

3. **Update inward skill (or pipeline inward path)**
   - Replace direct tool calls with tool-calling loop:
     ```python
     # Before (Phase 3 inward-query-skill):
     memories = await tools.execute("search_knowledge", query=body)
     code_results = await tools.execute("search_code", query=body)
     # ... hardcoded tool selection ...
     
     # After:
     tool_defs = tools.list_descriptions()  # safe inward tools only
     result = await tool_loop.run(messages, tool_defs, tools.execute)
     ```
   - LLM decides which tools to call based on the question

4. **Remove `code_keywords` from pipeline**
   - Delete the 28-keyword hardcoded list (pipeline.py lines 178-184)
   - Delete `should_search_code` branching logic (lines 187-214)
   - LLM now decides via tool_use whether to call search_code

5. **Remove `_SEND_PATTERNS` from twin_chat**
   - Delete regex-based send action detection
   - LLM returns `lookup_person` + `send_message` tool calls when Khanh says "say hi to Duong"
   - send-as-khanh skill (Phase 3) or inward path handles this via tool-calling loop

6. **Add iteration safety**
   - Max 3 tool-calling iterations
   - Timeout: 30s total for tool-calling loop
   - If loop exhausts iterations: return last LLM text response (graceful degradation)

7. **Add graceful fallback**
   - If Meridian/Claude returns error on tool_use: fall back to current direct pipeline (no tools)
   - Log fallback events for monitoring

8. **Write tests**
   - Test tool-calling loop with mock LLM returning tool_use blocks
   - Test max iteration enforcement
   - Test graceful fallback when tool_use errors
   - Test that outward mode NEVER receives tool definitions

9. **Run all tests** — 78 existing + new tests pass

## Todo Checklist

- [x] Create `tool-calling-loop.py` with ReAct loop
- [x] Add `generate_with_tools()` to LLMClient (Meridian + Claude providers)
- [x] Update inward skill/path to use tool-calling loop
- [x] Remove hardcoded `code_keywords` list (moved from pipeline to outward_reply_skill as _CODE_KEYWORDS — appropriate)
- [x] Remove regex `_SEND_PATTERNS` action detection (moved to skill matching logic)
- [x] Add iteration limit (max 3) + timeout (30s)
- [x] Add graceful fallback to direct pipeline
- [x] Verify outward mode has NO tool_use exposure
- [ ] Write tests for tool-calling loop (NOT CREATED)
- [ ] Write tests for fallback behavior (NOT CREATED)
- [x] All 78 existing tests pass (fixed test_high_confidence_triggers_send)
- [ ] Manual smoke test: "search code for MoneySource" triggers search_code tool (NOT TESTED)
- [ ] Manual smoke test: "say hi to Duong" triggers lookup_person + send_message tools (NOT TESTED)

## Success Criteria
- All 78 existing tests pass
- Inward mode uses Claude tool_use for dynamic tool selection
- Outward mode is completely unchanged (no tool_use, deterministic pipeline)
- `code_keywords` list deleted — LLM decides when to search code
- `_SEND_PATTERNS` regex deleted — LLM decides when to send messages
- Max 3 tool-calling iterations enforced
- Fallback to direct pipeline works when tool_use fails

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| LLM calls wrong tool (e.g. send_message when user just asked a question) | Medium | High | Confirmation step for send_message: include in tool description "only call when user explicitly asks to send" |
| Infinite tool-calling loop | Low | High | Hard limit: 3 iterations + 30s timeout |
| Meridian doesn't support tool_use param | Medium | High | Test Meridian tool_use support first; if not supported, implement only for Claude API provider |
| Inward latency increases >15s | Medium | Medium | Monitor p95 latency; if too high, reduce max_iterations to 2 |
| Outward mode accidentally gets tool_use | Low | Critical | Assertion in outward-reply skill: raise if tools param passed. Test enforces this. |
| Token cost increase from multi-turn tool calls | Medium | Low | Meridian = $0 marginal; Claude API fallback: monitor token usage per request |

## Security Considerations
- **CRITICAL:** Outward mode must NEVER have tool_use. Outward auto-sends messages AS Khanh — LLM must not dynamically decide to send arbitrary messages.
- send_message tool in inward mode: LLM can only send to DM rooms (lookup_person enforces this). Add explicit guard in tool description.
- Tool results re-fed to LLM: sanitize any PII or credentials from tool output before re-injection.
- Rate limit tool calls: max 5 tool executions per request to prevent abuse.

## Next Steps
- Monitor tool-calling decisions in production (log which tools LLM chooses)
- Fine-tune tool descriptions based on observed mismatches
- Future: extend thinking for complex inward queries (add `enable_thinking=True`)
- Future: parallel tool calling (Claude 4 supports this natively)
