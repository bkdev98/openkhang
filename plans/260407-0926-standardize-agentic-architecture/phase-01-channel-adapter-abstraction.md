# Phase 1: Channel Adapter Abstraction

## Context Links
- [Plan overview](plan.md)
- [OpenClaw channel separation](../reports/researcher-260407-0854-openclaw-architecture.md) — binding-based routing
- [Agent architecture patterns](../reports/researcher-260407-0854-agent-architecture-patterns.md) — three-layer adapter pattern

## Overview
- **Priority:** P1
- **Effort:** 1 day
- **Status:** Pending
- **Blockers:** None (parallel-safe with Phase 2)

Replace raw event dicts flowing through the system with a typed `CanonicalMessage` dataclass. Create an abstract `ChannelAdapter` interface and concrete adapters for Matrix (outward) and Dashboard (inward). Add a `ResponseRouter` that dispatches `AgentResult` to the correct adapter.

## Key Insights
- Current coupling: `agent_relay.py` manually constructs event dicts from Postgres rows (lines 156-166). `twin_chat.py` constructs different event dicts (line 61-66). `pipeline.py` reads raw dict keys throughout.
- OpenClaw pattern: bindings translate platform events to unified Gateway events — agent never sees platform-specific code.
- Critical safety: outward mode routing (auto-send vs draft) must remain unchanged.

## Requirements

### Functional
- F1: `CanonicalMessage` dataclass replaces all raw event dicts entering the pipeline
- F2: `ChannelAdapter` ABC with `normalize_inbound()` and `send_outbound()`
- F3: `MatrixChannelAdapter` wraps existing `agent_relay` event parsing + `matrix_sender.send()`
- F4: `DashboardChannelAdapter` wraps existing `twin_chat` event construction + direct return
- F5: `TelegramChannelAdapter` stub (raises NotImplementedError)
- F6: `ResponseRouter` takes `AgentResult` + `channel_type` → dispatches to correct adapter
- F7: Pipeline continues to accept raw dicts (backward compat shim) during transition

### Non-Functional
- NF1: All 78 tests pass without modification (adapter is additive)
- NF2: No performance regression (adapters are thin wrappers)

## Architecture

### Data Flow (Before)
```
agent_relay → dict construction → pipeline.process_event(dict) → AgentResult → inline routing
twin_chat  → dict construction → pipeline.process_event(dict) → AgentResult → inline routing
```

### Data Flow (After)
```
agent_relay → MatrixAdapter.normalize_inbound(row) → CanonicalMessage
twin_chat   → DashboardAdapter.normalize_inbound(question) → CanonicalMessage
                          ↓
              pipeline.process_event(CanonicalMessage) → AgentResult
                          ↓
              ResponseRouter.dispatch(AgentResult, channel_type) → adapter.send_outbound()
```

### CanonicalMessage Fields
```python
@dataclass
class CanonicalMessage:
    body: str
    channel: str              # 'matrix' | 'dashboard' | 'telegram' | 'cli'
    sender_id: str
    room_id: str = ""
    room_name: str = ""
    thread_event_id: str = ""
    event_id: str = ""
    is_group: bool = False
    is_mentioned: bool = False
    raw: dict = field(default_factory=dict)  # original payload for escape hatch
```

## Related Code Files

### Files to Create
| File | Purpose | Lines (est) |
|------|---------|-------------|
| `services/agent/channel-adapter.py` | ABC + CanonicalMessage dataclass | ~80 |
| `services/agent/matrix-channel-adapter.py` | Matrix adapter (wraps agent_relay parsing + matrix_sender) | ~90 |
| `services/agent/dashboard-channel-adapter.py` | Dashboard adapter (wraps twin_chat construction) | ~60 |
| `services/agent/telegram-channel-adapter.py` | Stub for future Telegram support | ~30 |
| `services/agent/response-router.py` | Dispatch AgentResult to correct adapter | ~60 |

### Files to Modify
| File | Change |
|------|--------|
| `services/agent/pipeline.py` | Accept CanonicalMessage OR dict (shim); move `_is_group_chat()` + `_is_mentioned()` to adapter |
| `services/dashboard/agent_relay.py` | Use MatrixChannelAdapter.normalize_inbound() instead of inline dict construction |
| `services/dashboard/twin_chat.py` | Use DashboardChannelAdapter.normalize_inbound() instead of inline dict |

### Files NOT Modified
| File | Reason |
|------|--------|
| `services/agent/classifier.py` | Reads `event` dict — shim provides same keys via CanonicalMessage |
| `services/agent/confidence.py` | Reads `event` dict — same shim |
| `services/agent/prompt_builder.py` | Reads `event` dict — same shim |
| `services/agent/matrix_sender.py` | Wrapped by MatrixChannelAdapter, not modified |
| `services/agent/room_lookup.py` | Called by twin_chat actions, not by adapter layer |

## Implementation Steps

1. **Create `services/agent/channel-adapter.py`**
   - Define `CanonicalMessage` dataclass with all fields above
   - Define `ChannelAdapter` ABC with `normalize_inbound()` → `CanonicalMessage` and `send_outbound(result: AgentResult, msg: CanonicalMessage)` → `str | None`
   - Add `to_legacy_dict()` method on CanonicalMessage for backward compatibility

2. **Create `services/agent/matrix-channel-adapter.py`**
   - Move event dict construction logic from `agent_relay.py` lines 156-166 into `normalize_inbound(row, metadata)`
   - Move `_is_group_chat()` and `_is_mentioned()` from `pipeline.py` into adapter (set fields on CanonicalMessage)
   - `send_outbound()` delegates to existing `MatrixSender.send()`

3. **Create `services/agent/dashboard-channel-adapter.py`**
   - `normalize_inbound(question, session_id)` produces CanonicalMessage with channel='dashboard'
   - `send_outbound()` returns reply_text directly (no Matrix send)

4. **Create `services/agent/telegram-channel-adapter.py`**
   - Stub class, all methods raise `NotImplementedError("Telegram adapter not yet implemented")`

5. **Create `services/agent/response-router.py`**
   - Registry mapping channel → adapter instance
   - `dispatch(result, msg)` calls correct adapter's `send_outbound()`
   - For outward/Matrix: preserves exact auto-send vs draft logic from `pipeline._route()`

6. **Update `services/agent/pipeline.py`**
   - Add overloaded `process_event()` that accepts `CanonicalMessage`
   - If raw dict passed, wrap in `CanonicalMessage` via shim (backward compat)
   - Move `_is_group_chat()` and `_is_mentioned()` to channel adapter (but keep as private fallback during transition)

7. **Update `services/dashboard/agent_relay.py`**
   - Import MatrixChannelAdapter; use `normalize_inbound()` instead of inline dict
   - Pass CanonicalMessage to pipeline

8. **Update `services/dashboard/twin_chat.py`**
   - Import DashboardChannelAdapter; use `normalize_inbound()` instead of inline dict

9. **Run tests** — all 78 must pass

## Todo Checklist

- [ ] Create `CanonicalMessage` dataclass + `ChannelAdapter` ABC
- [ ] Create `MatrixChannelAdapter` (normalize + send)
- [ ] Create `DashboardChannelAdapter` (normalize + return)
- [ ] Create `TelegramChannelAdapter` stub
- [ ] Create `ResponseRouter` dispatcher
- [ ] Update `pipeline.py` to accept CanonicalMessage (with dict shim)
- [ ] Update `agent_relay.py` to use MatrixChannelAdapter
- [ ] Update `twin_chat.py` to use DashboardChannelAdapter
- [ ] All 78 tests pass
- [ ] Manual smoke test: dashboard inward chat works
- [ ] Manual smoke test: outward pipeline (if Matrix bridge available)

## Success Criteria
- All 78 tests pass
- `CanonicalMessage.to_legacy_dict()` produces identical dict to current inline construction
- New event sources (Telegram) can be added by creating one adapter file, zero pipeline changes
- No behavioral change in auto-send vs draft routing

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Dict shim introduces subtle key mismatch | Medium | High | Unit test `to_legacy_dict()` output matches current inline dicts exactly |
| `_is_group_chat()` logic diverges between adapter and pipeline | Low | Medium | Delete pipeline copy once adapter is wired; single source of truth |
| `agent_relay.py` late imports break with adapter | Low | Low | Adapter uses same late-import pattern |

## Security Considerations
- CanonicalMessage.raw stores original payload — ensure no PII leaks to logging
- Adapter normalization must sanitize sender_id same as current pipeline
- TelegramChannelAdapter stub must NOT expose any endpoints until implemented

## Next Steps
- After Phase 1: adapters are available for Phase 3 skills to use (send_as_khanh skill calls adapter)
- After Phase 1: ResponseRouter can be injected into Phase 4 tool-calling loop
