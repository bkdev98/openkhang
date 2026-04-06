---
phase: 4
title: Workflow Engine
status: Pending
priority: P2
effort: 6h
depends_on: [3]
---

# Phase 4: Workflow Engine

## Context Links

- Phase 3: [Dual-Mode Agent](phase-03-dual-mode-agent.md) — agent pipeline required
- Existing orchestrator: `skills/openkhang-status/`, `skills/code-session/`
- Existing hooks: `hooks/hooks.json` — SessionStart, UserPromptSubmit

## Overview

YAML-defined state machines that orchestrate multi-step workflows across tools. Example: chat message mentions a bug → create Jira ticket → assign → start code session → watch pipeline → report back in chat. Three-tier autonomy model governs what the engine can do automatically.

## Key Insights

- Event-driven: workflows trigger on events, not polling
- State machines keep workflow resumable after failures
- Three-tier autonomy: Tier 1 (read-only, auto), Tier 2 (reversible, confidence-gated), Tier 3 (irreversible, always approval)
- Append-only audit log for every action — compliance and debugging
- Entity correlation: link Jira ticket ↔ GitLab MR ↔ Chat thread ↔ Confluence page within workflow context

## Requirements

### Functional
- F1: YAML workflow definitions with states, transitions, conditions
- F2: Event triggers: chat_message, jira_update, pipeline_status, timer, manual
- F3: Actions: send_chat, create_jira, update_jira, start_code_session, query_memory
- F4: Three-tier autonomy enforcement per action type
- F5: Append-only audit log (Postgres table)
- F6: Workflow state persistence — resume after restart
- F7: Entity correlation: auto-link related items created during workflow

### Non-Functional
- NF1: Workflow state transition <100ms
- NF2: Audit log queryable by workflow_id, entity_id, time range
- NF3: Failed workflows retry with exponential backoff, max 3 attempts

## Architecture

```
Events (Redis) ──→ Workflow Engine
                        │
                   ┌────┴────┐
                   │ Matcher  │ ← YAML workflow definitions
                   │ (trigger │
                   │  eval)   │
                   └────┬────┘
                        │ matched
                        ▼
                   ┌──────────┐
                   │  State   │ ← Postgres (workflow_instances table)
                   │  Machine │
                   │  Runner  │
                   └────┬────┘
                        │
              ┌─────────┼─────────┐
              ▼         ▼         ▼
         Tier 1     Tier 2     Tier 3
         (auto)   (gated)    (approval)
              │         │         │
              └─────────┼─────────┘
                        ▼
                   Action Executor
                   (chat, jira, gitlab, memory)
                        │
                        ▼
                   Audit Log (append-only)
```

### Data Flow

1. Event arrives on Redis `openkhang:events`
2. Matcher evaluates all workflow triggers against event
3. Matched workflow instantiated: `workflow_instances(id, workflow_name, state, context, created_at, updated_at)`
4. State machine transitions: evaluate conditions, execute actions
5. Each action checked against autonomy tier:
   - T1 (query_memory, read_jira, read_chat): execute immediately
   - T2 (send_chat, update_jira_status): execute if confidence > threshold, else queue for approval
   - T3 (create_jira, merge_mr, deploy): always queue for approval
6. Action result → update state → check next transition
7. Every action logged: `audit_log(id, workflow_id, action, tier, input, output, approved_by, timestamp)`

## Related Code Files

### Create
- `services/workflow/__init__.py`
- `services/workflow/engine.py` — Main engine: match triggers, run state machines
- `services/workflow/state_machine.py` — YAML-driven state machine runner
- `services/workflow/actions.py` — Action registry (send_chat, create_jira, etc.)
- `services/workflow/autonomy.py` — Three-tier enforcement + approval queue
- `services/workflow/audit.py` — Append-only audit log
- `services/workflow/schema.sql` — workflow_instances + audit_log tables
- `config/workflows/bug-from-chat.yaml` — Example: chat bug report → Jira → code session
- `config/workflows/daily-standup.yaml` — Example: morning summary → chat report
- `config/workflows/pipeline-alert.yaml` — Example: pipeline fail → chat notify → auto-fix

### Modify
- `docker-compose.yml` — Add workflow service (or integrate into agent service)

### No Deletes

## Implementation Steps

1. **Define Workflow YAML Schema**
   ```yaml
   # config/workflows/bug-from-chat.yaml
   name: bug-from-chat
   description: "Chat bug report → Jira ticket → code session"
   trigger:
     event: chat_message
     conditions:
       - intent: bug_report
       - confidence: ">0.7"
   states:
     start:
       actions:
         - type: create_jira
           tier: 3  # needs approval
           params:
             project: "{{context.jira_project}}"
             summary: "{{event.summary}}"
             description: "{{event.body}}"
       transitions:
         - on: action_approved
           to: coding
         - on: action_rejected
           to: cancelled
     coding:
       actions:
         - type: start_code_session
           tier: 3
           params:
             ticket: "{{actions.create_jira.result.key}}"
       transitions:
         - on: session_complete
           to: notify
     notify:
       actions:
         - type: send_chat
           tier: 2
           params:
             room: "{{event.room_id}}"
             message: "Filed {{actions.create_jira.result.key}} and started working on it."
       transitions:
         - on: action_complete
           to: done
     done:
       terminal: true
     cancelled:
       terminal: true
   ```

2. **Build State Machine Runner**
   - Load YAML definition, validate schema
   - Maintain current state + context dict in Postgres
   - On transition: evaluate conditions, execute action, log to audit
   - Support template variables: `{{event.field}}`, `{{context.field}}`, `{{actions.step.result.field}}`
   - Handle async actions: set state to `waiting_approval` or `waiting_action`

3. **Build Action Registry**
   - Each action = async function with standardized input/output
   - Actions call existing tools: `jira issue create`, `glab mr create`, Matrix API, memory client
   - Actions return structured result for template variable injection
   - Actions wrapped with tier check before execution

4. **Build Autonomy Enforcement**
   - Action tiers defined per action type (hardcoded, not configurable — safety first)
   - Tier 1: `query_memory`, `read_jira`, `read_gitlab`, `read_chat` → always auto
   - Tier 2: `send_chat`, `update_jira_status`, `add_comment` → confidence-gated
   - Tier 3: `create_jira`, `merge_mr`, `deploy`, `delete_*` → always approval
   - Approval queue in Postgres: `approval_queue(id, workflow_id, action, params, status, requested_at, resolved_at)`
   - Dashboard shows pending approvals (Phase 5)

5. **Build Audit Log**
   - Table: `audit_log(id serial, workflow_id int, action varchar, tier int, input jsonb, output jsonb, status varchar, approved_by varchar, created_at timestamptz)`
   - Append-only: never update or delete
   - Index on workflow_id, created_at for fast queries

6. **Wire to Event Bus**
   - Subscribe to `openkhang:events`
   - On event: iterate all workflow definitions, evaluate triggers
   - If match: create workflow instance, start execution
   - Publish workflow state changes to `openkhang:workflow_updates` (dashboard subscribes)

7. **Create Example Workflows**
   - `bug-from-chat.yaml`: chat message classified as bug → create Jira → assign → notify
   - `daily-standup.yaml`: timer trigger (9am) → query memory for yesterday's work → generate summary → send to chat
   - `pipeline-alert.yaml`: pipeline failure event → notify in chat → attempt auto-fix if pattern matches

8. **Write Tests**
   - Unit: YAML parsing + validation
   - Unit: state machine transitions with mock actions
   - Unit: autonomy tier enforcement (T3 action without approval → blocked)
   - Integration: full workflow execution with mock event → verify audit log entries

## TODO

- [ ] Define YAML workflow schema
- [ ] Create `services/workflow/engine.py`
- [ ] Create `services/workflow/state_machine.py`
- [ ] Create `services/workflow/actions.py`
- [ ] Create `services/workflow/autonomy.py`
- [ ] Create `services/workflow/audit.py`
- [ ] Create `services/workflow/schema.sql`
- [ ] Create 3 example workflow YAML files
- [ ] Wire to Redis event bus
- [ ] Write unit + integration tests

## Success Criteria

1. YAML workflow parses and validates without errors
2. `bug-from-chat` workflow creates a Jira ticket (after approval) when triggered by chat event
3. T3 actions always blocked until explicit approval
4. T2 actions auto-execute when confidence > threshold
5. Audit log contains complete history of all workflow actions
6. Workflow resumes correctly after service restart

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| YAML schema too complex for users | Medium | Low | Start with 3 pre-built workflows, KISS |
| State machine deadlock | Low | Medium | Timeout on waiting states (30min default), auto-cancel |
| Action executor errors crash workflow | Medium | Medium | Try-catch per action, transition to error state, retry logic |
| Approval queue ignored (drafts pile up) | Medium | Medium | Dashboard notifications, daily digest, escalation after 4h |

## Security Considerations

- T3 actions MUST require approval — never bypass via config
- Audit log is append-only — no delete API exposed
- Workflow YAML loaded from config/ directory only — never from user input
- Template variable injection sanitized (no code execution in templates)
- Rate limit workflow creation: max 10 active workflows simultaneously
