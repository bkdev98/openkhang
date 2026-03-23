---
name: sprint-prioritize
description: >-
  This skill should be invoked with "/sprint-prioritize" to analyze and
  re-prioritize the user's assigned Jira tickets based on urgency, blockers,
  sprint deadline, and dependencies. Suggests optimal work order and flags
  at-risk items.
argument-hint: "[--suggest] [--apply]"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
version: 0.1.0
---

# Sprint Prioritize

Analyze and prioritize user's sprint tickets.

## Arguments

- `--suggest` — Show prioritized list with reasoning (default)
- `--apply` — Suggest AND update Jira issue priorities/order

## Execution Flow

### 1. Fetch User's Sprint Issues

```bash
jira issue list --jql "sprint in openSprints() AND assignee = currentUser() AND status != Done" --json
```

### 2. Fetch Linked Issues

For each issue, check linked/blocked issues:
```bash
jira issue view PROJ-123 --json
```

Extract: blockers, blocked-by, relates-to, subtasks.

### 3. Analyze and Prioritize

Apply priority algorithm (from jira-knowledge):
1. Blockers first (issues blocking teammates)
2. Urgency (P0 > P1 > P2 > P3)
3. Sprint deadline proximity
4. Quick wins (small story points when time allows)
5. Dependency chain ordering

### 4. Display Prioritized List

```
🎯 Recommended Work Order (5 items, 15 SP remaining)

Sprint ends in 7 days — need ~2.1 SP/day velocity

 #  │ Key       │ SP │ Priority │ Why
────┼───────────┼────┼──────────┼─────────────────────────────
 1  │ PROJ-123  │ 5  │ 🔴 P1   │ Blocks PROJ-145 + PROJ-148 (team blocked)
 2  │ PROJ-132  │ 2  │ 🟡 P2   │ Quick win, unblocks PROJ-134 review
 3  │ PROJ-128  │ 5  │ 🟡 P2   │ Large item, start early to finish on time
 4  │ PROJ-125  │ 3  │ 🟢 P3   │ No blockers, medium effort
────┼───────────┼────┼──────────┼─────────────────────────────
    │           │ 15 │          │ ~7 days at 2.1 SP/day ✅ achievable

⚠️ Risks:
- PROJ-128 (5 SP) needs 2-3 days, start by Wed to finish on time
- If PROJ-123 takes >2 days, escalate — 2 teammates blocked
```

### 5. Apply (if --apply)

Update issue priorities in Jira:
```bash
jira issue edit PROJ-123 --priority "Highest" --no-input
```

Reorder backlog if board supports ranking.

### 6. Integration with Chat

If urgent ticket detected via Google Chat:
- Re-run prioritization including the new ticket
- Suggest where it fits in the work order
- Flag if sprint is now at risk
