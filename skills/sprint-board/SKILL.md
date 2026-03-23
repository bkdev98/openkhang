---
name: sprint-board
description: >-
  This skill should be invoked with "/sprint-board" to display the current
  Jira sprint board with status columns, burndown progress, and sprint
  health indicators. Shows all team tickets grouped by status.
argument-hint: "[--mine] [--team] [--burndown]"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
version: 0.1.0
---

# Sprint Board

Display current sprint board and burndown status.

## Arguments

- `--mine` — Show only tickets assigned to user (default)
- `--team` — Show all team tickets in the sprint
- `--burndown` — Include burndown chart (story points over time)

## Execution Flow

### 1. Load Config

Read `.claude/openkhang.local.md` for project key, board ID, and account.

If not configured, prompt user for:
- Jira project key (e.g., PROJ)
- Board ID (list boards with `jira board list --json` and let user pick)

### 2. Fetch Current Sprint

```bash
jira sprint list --board BOARD_ID --current --json
```

Extract sprint name, start date, end date, sprint goal.

### 3. Fetch Sprint Issues

```bash
jira issue list --jql "sprint in openSprints() AND project = PROJ" --json
```

If `--mine` (default): add `AND assignee = currentUser()` to JQL.

### 4. Display Board

```
📋 Sprint: Sprint 24 (Mar 18 - Mar 31) — Day 7/14
🎯 Goal: Complete auth refactor and payment integration

📊 Burndown: 34/50 SP remaining (68%) — ⚠️ slightly behind

┌─────────────┬──────────────┬──────────────┬──────────────┐
│  TO DO (3)  │ IN PROG (4)  │ REVIEW (2)   │  DONE (8)    │
├─────────────┼──────────────┼──────────────┼──────────────┤
│ PROJ-145 3p │ PROJ-123 5p  │ PROJ-130 3p  │ PROJ-110 2p  │
│ Auth config │ Login bug    │ Pay API      │ DB migrate   │
│             │              │              │              │
│ PROJ-148 2p │ PROJ-125 3p  │ PROJ-134 2p  │ PROJ-112 3p  │
│ Token exp   │ OAuth flow   │ Tests        │ User model   │
│             │              │              │              │
│ PROJ-150 1p │ PROJ-128 5p  │              │ ...+6 more   │
│ Docs update │ Payment UI   │              │              │
│             │              │              │              │
│             │ PROJ-132 2p  │              │              │
│             │ Error handle │              │              │
└─────────────┴──────────────┴──────────────┴──────────────┘

⚠️ At Risk: PROJ-128 (5p, Payment UI) — in progress 4 days, no PR yet
🔴 Blocked: PROJ-145 (Auth config) — blocked by PROJ-123
```

### 5. Sprint Health

Calculate and display:
- Days elapsed / total sprint days
- Story points completed vs total
- Velocity trend (compare to last 3 sprints if available)
- At-risk items (large items still in To Do or In Progress late in sprint)
- Blocked items (issues with blocker links)

### 6. Update Cache

Save sprint data to state file for offline reference.
