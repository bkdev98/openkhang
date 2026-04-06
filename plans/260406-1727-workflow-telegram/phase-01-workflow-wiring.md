# Phase 1: Wire Workflow Engine to Event Stream

## Context Links
- Workflow engine: `services/workflow/workflow_engine.py`
- Agent relay: `services/dashboard/agent_relay.py`
- YAML workflows: `config/workflows/chat-to-jira.yaml`, `config/workflows/pipeline-failure.yaml`
- Audit log: `services/workflow/audit_log.py`

## Overview
- **Priority**: P1
- **Status**: Pending
- **Effort**: 1.5h
- **Scope**: Single file modification (`agent_relay.py`)

The WorkflowEngine is fully implemented (engine, state machine, action executor, persistence, audit log) but has zero callers. Wire it into `agent_relay.py` after `pipeline.process_event()`.

## Key Insight: Event Type Mapping

**Critical mismatch to resolve**: The YAML workflow `chat-to-jira.yaml` triggers on `event: chat_message`, but the event dict built in `agent_relay.py` has no `type` field. The `_match_workflows()` method reads `event.get("type") or event.get("event_type", "")`.

**Solution**: Add `"type": "chat_message"` to the event dict in agent_relay before passing to workflow engine. This is the correct semantic type — the events table has `event_type: message.received` (transport-level), but the workflow trigger uses domain-level types.

Also enrich the event with pipeline result fields so workflow conditions can use them:
- `intent` from `AgentResult.intent`
- `action` from `AgentResult.action`
- `confidence` from `AgentResult.confidence`

## Data Flow

```
events table (source=chat, event_type=message.received)
    │
    ▼ (poll, build event dict)
agent_relay.py
    │
    ├─→ pipeline.process_event(event) → AgentResult
    │
    ├─→ enrich event: type=chat_message, intent, action, confidence
    │
    └─→ engine.handle_event(enriched_event) → list[WorkflowAction]
            │
            ├─→ audit_log (automatic, inside engine)
            └─→ Redis publish openkhang:events (new code in agent_relay)
```

## Related Code Files

**Modify:**
- `services/dashboard/agent_relay.py` — add workflow engine init + call after pipeline

**Read-only (no changes):**
- `services/workflow/workflow_engine.py`
- `services/workflow/action_executor.py`
- `services/workflow/state_machine.py`
- `services/workflow/audit_log.py`
- `services/workflow/workflow_persistence.py`

## Implementation Steps

### Step 1: Add WorkflowEngine initialization (after pipeline init, ~line 63)

```python
# After pipeline init, before the polling loop
from services.workflow.workflow_engine import WorkflowEngine

engine = WorkflowEngine(
    memory_client=memory,
    agent_pipeline=pipeline,
    database_url=str(config.database_url),
    workflows_dir="config/workflows",
)
await engine.connect()
await engine.load_workflows()
logger.info("agent_relay: workflow engine ready (%d workflows)", len(engine._workflows))
```

### Step 2: Add Redis client for publishing workflow actions

```python
import redis.asyncio as aioredis

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = aioredis.from_url(redis_url)
```

### Step 3: After pipeline.process_event(), call workflow engine (~line 129)

```python
result = await pipeline.process_event(event)
logger.info(...)

# Enrich event for workflow matching
workflow_event = {
    **event,
    "type": "chat_message",
    "intent": result.intent,
    "action": result.action,
    "confidence": result.confidence,
}

# Run through workflow engine
try:
    actions = await engine.handle_event(workflow_event)
    for wa in actions:
        logger.info(
            "agent_relay: workflow '%s' action=%s state=%s success=%s",
            wa.workflow_name, wa.action_type, wa.state_name,
            wa.result.success,
        )
        # Publish to Redis for dashboard SSE + Telegram notifier
        await redis_client.publish(
            "openkhang:events",
            json.dumps({
                "source": "workflow",
                "event_type": "workflow.action",
                "workflow_name": wa.workflow_name,
                "workflow_id": wa.workflow_id,
                "action_type": wa.action_type,
                "state": wa.state_name,
                "success": wa.result.success,
                "needs_approval": wa.result.needs_approval,
                "output": wa.result.output,
            }),
        )
except Exception as exc:
    logger.error("agent_relay: workflow error: %s", exc)
```

### Step 4: Clean shutdown — add engine.close() to exception/finally handling

Since `run_agent_relay` runs forever in a task, add try/finally:

```python
try:
    # ... existing polling loop ...
finally:
    await engine.close()
    await redis_client.close()
```

## Todo List

- [ ] Add WorkflowEngine import and initialization after pipeline init
- [ ] Add Redis async client for publishing
- [ ] Add `type: chat_message` enrichment to event dict after pipeline processing
- [ ] Call `engine.handle_event()` after `pipeline.process_event()`
- [ ] Publish workflow actions to `openkhang:events` Redis channel
- [ ] Wrap workflow call in try/except (never crash relay on workflow error)
- [ ] Add try/finally for engine.close() and redis_client.close()
- [ ] Test: send chat with "bug" keyword, verify audit_log row created
- [ ] Test: verify workflow action appears in dashboard SSE feed

## Failure Modes

| Failure | Impact | Handling |
|---------|--------|----------|
| Workflow engine fails to connect (no DB) | Relay continues without workflows | Log warning, set `engine = None`, skip workflow calls |
| `handle_event` throws | Relay poll continues | try/except around workflow call, log error |
| Redis publish fails | Dashboard misses workflow event | Log warning, continue (audit_log still has record) |
| YAML workflow malformed | That workflow skipped | Engine already logs warning and skips |
| Workflow enters infinite loop | Capped at 20 transitions | Built into `_drive()` already |

## Security Considerations

- No new attack surface (no new endpoints)
- Workflow actions use existing tier system (tier 3 = human approval required)
- Audit log provides non-repudiation trail

## Success Criteria

1. `SELECT * FROM audit_log` shows entries after a chat message with bug keywords
2. Redis monitor shows `openkhang:events` messages with `source: workflow`
3. Dashboard SSE feed shows workflow action events
4. Agent relay does NOT crash if workflow engine is unavailable
