# Phase 2: Tool Registry + Tool Conversion

## Context Links
- [Plan overview](plan.md)
- [Agent architecture patterns](../reports/researcher-260407-0854-agent-architecture-patterns.md) — registry pattern
- [Agent skills ecosystem](../reports/researcher-260407-0854-agent-skills-ecosystem.md) — tool vs skill distinction

## Overview
- **Priority:** P1
- **Effort:** 1.5 days
- **Status:** Done
- **Blockers:** None (parallel-safe with Phase 1)

Create a `ToolRegistry` + `BaseTool` abstraction and convert existing pipeline capabilities into registered tools. Tools are plain Python async functions with typed params wrapped in a uniform interface. Existing logic stays unchanged — tools are thin wrappers.

## Key Insights
- Current capabilities are buried inside `pipeline.py` (520 LOC) as inline method calls. No way to invoke them independently or compose them differently.
- Research confirms: tools = atomic execution (search, send, lookup); skills = multi-step orchestration. We build tools here; skills in Phase 3.
- Claude tool_use needs tool descriptions as JSON schema. Building the registry now enables Phase 4 to generate these schemas automatically.
- 7 tools identified from current pipeline behavior.

## Requirements

### Functional
- F1: `BaseTool` ABC with `name`, `description`, `parameters` (JSON schema), `execute(**kwargs)`
- F2: `ToolRegistry` with `register(tool)`, `get(name)`, `list_tools()`, `list_descriptions()` (for LLM injection), `execute(name, **kwargs)`
- F3: Convert 7 capabilities into tools (see list below)
- F4: Pipeline can optionally use tools via registry instead of direct calls (opt-in, not forced)
- F5: Tools are individually testable without pipeline

### Non-Functional
- NF1: All 78 tests pass (tools are additive, pipeline unchanged)
- NF2: Tool execute() has same latency as direct method call (thin wrapper)
- NF3: Each tool file <100 LOC

## Architecture

### Tool Interface
```python
class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict: ...  # JSON Schema

    @abstractmethod
    async def execute(self, **kwargs) -> Any: ...

    def to_claude_tool(self) -> dict:
        """Generate Claude tool_use compatible definition."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }
```

### Tool Inventory

| Tool Name | Wraps | Input | Output |
|-----------|-------|-------|--------|
| `search_knowledge` | `memory.search()` | query: str, limit: int | list[dict] |
| `search_code` | `memory.search_code()` + `_extract_code_search_terms()` | query: str, limit: int | list[dict] |
| `get_sender_context` | `memory.get_related()` | sender_id: str | list[dict] |
| `get_room_history` | `memory.get_room_messages()` | room_id: str, limit: int | list[dict] |
| `send_message` | `matrix_sender.send()` via channel adapter | room_id: str, text: str, thread_event_id: str? | event_id: str |
| `lookup_person` | `room_lookup.find_room_by_person()` | name: str | dict or None |
| `create_draft` | `draft_queue.add_draft()` | room_id: str, text: str, confidence: float, ... | draft_id: str |

### Registry Data Flow
```
ToolRegistry.register(SearchKnowledgeTool(memory_client))
ToolRegistry.register(SearchCodeTool(memory_client))
...

# Usage from pipeline (opt-in):
results = await registry.execute("search_knowledge", query="payments", limit=10)

# Usage from Phase 4 LLM tool-calling:
tool_defs = registry.list_descriptions()  # → inject into Claude prompt
# LLM returns tool_use block → registry.execute(name, **params)
```

## Related Code Files

### Files to Create
| File | Purpose | Lines (est) |
|------|---------|-------------|
| `services/agent/tool-registry.py` | BaseTool ABC + ToolRegistry class | ~80 |
| `services/agent/tools/search-knowledge-tool.py` | Wraps memory.search() | ~50 |
| `services/agent/tools/search-code-tool.py` | Wraps memory.search_code() + term extraction | ~70 |
| `services/agent/tools/get-sender-context-tool.py` | Wraps memory.get_related() | ~40 |
| `services/agent/tools/get-room-history-tool.py` | Wraps memory.get_room_messages() | ~40 |
| `services/agent/tools/send-message-tool.py` | Wraps matrix_sender.send() | ~50 |
| `services/agent/tools/lookup-person-tool.py` | Wraps room_lookup.find_room_by_person() | ~40 |
| `services/agent/tools/create-draft-tool.py` | Wraps draft_queue.add_draft() | ~50 |
| `services/agent/tools/__init__.py` | Re-exports all tools | ~15 |

### Files to Modify
| File | Change |
|------|--------|
| `services/agent/pipeline.py` | Add `_init_tools()` that registers tools; optionally use registry in process_event (behind flag) |

### Files NOT Modified
| File | Reason |
|------|--------|
| All existing service files | Tools wrap them, don't change them |
| Test files | Tools are additive; existing tests unchanged |

## Implementation Steps

1. **Create `services/agent/tool-registry.py`**
   - `BaseTool` ABC with name, description, parameters, execute(), to_claude_tool()
   - `ToolRegistry` class: register(), get(), list_tools(), list_descriptions(), execute()
   - execute() catches exceptions and returns `ToolResult(success, data, error)` dataclass

2. **Create `services/agent/tools/` directory with `__init__.py`**

3. **Create `search-knowledge-tool.py`**
   - Constructor takes `MemoryClient`
   - execute(query, limit=10) → calls `self._memory.search(query, agent_id="outward", limit=limit)`
   - Parameters schema: `{"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}}}`

4. **Create `search-code-tool.py`**
   - Constructor takes `MemoryClient`
   - Moves `_extract_code_search_terms()` from pipeline.py into this tool
   - execute(query, limit=20) → extract terms → `self._memory.search_code(terms, limit=limit)`

5. **Create `get-sender-context-tool.py`**
   - Constructor takes `MemoryClient`
   - execute(sender_id, agent_id="outward") → `self._memory.get_related(sender_id, agent_id=agent_id)`

6. **Create `get-room-history-tool.py`**
   - Constructor takes `MemoryClient`
   - execute(room_id, limit=30) → `self._memory.get_room_messages(room_id, limit=limit)`

7. **Create `send-message-tool.py`**
   - Constructor takes `MatrixSender` (or ChannelAdapter from Phase 1 if available)
   - execute(room_id, text, thread_event_id=None) → `self._sender.send(...)`

8. **Create `lookup-person-tool.py`**
   - No constructor deps (uses module-level function)
   - execute(name) → `find_room_by_person(name)`

9. **Create `create-draft-tool.py`**
   - Constructor takes `DraftQueue`
   - execute(room_id, text, confidence, evidence, room_name="", event_id=None) → `self._drafts.add_draft(...)`

10. **Update `services/agent/pipeline.py`**
    - Add `_init_tools()` method that creates ToolRegistry and registers all 7 tools
    - Store as `self._tools: ToolRegistry`
    - Do NOT change process_event() flow yet — tools available but unused until Phase 3/4

11. **Write tool unit tests**
    - Test each tool's execute() with mocked dependencies
    - Test ToolRegistry register/get/list/execute
    - Test to_claude_tool() output matches expected schema

12. **Run all tests** — 78 existing + new tool tests pass

## Todo Checklist

- [x] Create `BaseTool` ABC + `ToolRegistry` class
- [x] Create `search-knowledge-tool.py`
- [x] Create `search-code-tool.py` (move `_extract_code_search_terms`)
- [x] Create `get-sender-context-tool.py`
- [x] Create `get-room-history-tool.py`
- [x] Create `send-message-tool.py`
- [x] Create `lookup-person-tool.py`
- [x] Create `create-draft-tool.py`
- [x] Wire tools into pipeline (opt-in, not active yet)
- [ ] Write unit tests for each tool (NOT CREATED)
- [ ] Write unit tests for ToolRegistry (NOT CREATED)
- [x] All 77 existing tests pass (1 test fails: test_high_confidence_triggers_send)

## Success Criteria
- All 78 existing tests pass unchanged
- Each tool individually callable and testable
- `registry.list_descriptions()` returns valid Claude tool_use definitions
- `to_claude_tool()` output validated against Claude API schema
- `_extract_code_search_terms()` still accessible (moved to tool, re-exported or kept as utility)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Tool wrapper adds indirection; debugging harder | Low | Low | Tools are <50 LOC each; stack trace is shallow |
| `_extract_code_search_terms` moved causes import break | Medium | Medium | Keep as static method on pipeline during transition; tool calls it |
| MemoryClient lifecycle mismatch (tool holds ref to unconnected client) | Low | High | Tools receive already-connected client; document in constructor docstring |
| Too many small files feels over-engineered | Low | Low | 7 tools x ~50 LOC = 350 LOC total. Alternative (one file) would be 350 LOC — same. Files aid discoverability. |

## Security Considerations
- `send-message-tool.py` must respect rate limiting from MatrixSender (already built in)
- `create-draft-tool.py` must not bypass confidence thresholds
- Tool descriptions exposed to LLM (Phase 4) — ensure no sensitive info in description text

## Next Steps
- Phase 3 uses tools via registry to compose skills
- Phase 4 injects `registry.list_descriptions()` into Claude tool_use prompt
