## Code Review: Agentic Architecture Refactoring

### Scope
- 21 new files, 4 modified files
- Focus: channel adapters, tool/skill registries, tool-calling loop, pipeline dispatch

### Overall Assessment
Clean, well-structured refactoring. Abstractions are well-defined. Backward compat preserved via `to_legacy_dict()` bridge and `_process_inline()` fallback. No regressions expected for existing 78 tests.

### Critical Issues

**1. `send_message` tool exposed to LLM in inward ReAct loop**
`_EXCLUDED_INWARD_TOOLS = {"create_draft"}` — but `send_message` is NOT excluded. The LLM can autonomously send messages to ANY Matrix room via the tool-calling loop. This is the biggest security concern: a prompt injection in an inward query could trigger the LLM to call `send_message` with arbitrary content. The `SendAsKhanhSkill` has explicit intent matching, but the `InwardQuerySkill` hands `send_message` to the LLM with no guardrails.

**Recommendation:** Add `"send_message"` to `_EXCLUDED_INWARD_TOOLS` in `inward_query_skill.py`. Only `SendAsKhanhSkill` should use `send_message`, and it does so programmatically (not via LLM tool_use).

### High Priority

**2. DB connection leak in `SendAsKhanhSkill._enrich_with_context()`** (line 97-104)
Raw `asyncpg.connect()` without `try/finally` on `conn.close()`. If `conn.fetch()` raises, connection leaks. Use `async with asyncpg.connect(...) as conn:` or wrap in try/finally.

**3. `_detect_group_chat()` returns True for ALL non-empty room names** (line 165)
`return bool(room_name)` means any DM with a display name is treated as a group chat. This could cause outward replies to be incorrectly skipped in DMs that have a room name set.

**4. Duplicate classification in skills**
`OutwardReplySkill.execute()` re-classifies intent (line 58) even though `process_event()` already classified it. Intent is computed but not passed to skills — wasted LLM/CPU and potential mode/intent divergence.

### Medium Priority

**5. `messages` list mutated in-place** by `run_tool_calling_loop()` (lines 107, 135)
Callers may not expect this. The messages list grows with each iteration. If the caller retains a reference, state leaks between calls. Document or `.copy()` at entry.

**6. Private attr hack on AgentResult** (`send_as_khanh_skill.py:79`)
`result._send_action_result = action_result` — dynamically attaches untyped attribute. Add `send_action_result` to `AgentResult` dataclass as `Optional[dict] = None`.

**7. Redundant duplicate search in `_gather_memories()`** (`inward_query_skill.py:146`)
Searches `agent_id="inward"` twice with identical params (lines 144 and 146). The dedup via `seen_ids` masks it — second search is wasted.

### Positive Observations
- Outward mode correctly stays deterministic — no tool_use, structured JSON output
- Tool-calling loop has both iteration cap (3) and timeout (30s) — good defense
- `ToolRegistry.execute()` never raises — always returns `ToolResult`
- Fallback from tool-calling to direct RAG in inward skill is solid
- Clean ABC abstractions with clear contracts

### Recommended Actions
1. **BLOCK:** Exclude `send_message` from inward tool-calling loop
2. Fix asyncpg connection leak in `_enrich_with_context()`
3. Reconsider `_detect_group_chat()` logic for DMs with display names
4. Pass classified intent to skills to avoid re-classification
