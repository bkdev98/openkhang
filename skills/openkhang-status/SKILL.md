---
name: openkhang-status
description: >-
  This skill should be invoked with "/openkhang-status" to display a unified
  dashboard of all work tools — Google Chat pending messages, Jira sprint
  status, active code sessions, and pipeline health. Quick overview of
  everything happening.
argument-hint: ""
allowed-tools: ["Bash", "Read", "Write", "Edit"]
version: 0.1.0
---

# OpenKhang Status Dashboard

Unified view across all integrated tools.

## Execution Flow

### 1. Load All State

Read `.claude/openkhang.local.md` for all block states.

### 2. Fetch Live Data

Run in parallel where possible:

```bash
# Chat: pending drafts (from state file, no API call needed)
# Jira: current sprint quick stats
jira issue list --jql "sprint in openSprints() AND assignee = currentUser()" --json
# GitLab: active pipelines and MRs
glab mr list --assignee=@me --json
glab ci list --json | head -5
```

### 3. Display Dashboard

```
╔══════════════════════════════════════════════════════════╗
║                   🏠 OpenKhang Status                    ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  💬 Google Chat                                          ║
║  ├─ 2 pending draft replies (/chat-reply to review)      ║
║  ├─ 1 urgent message from Alice                          ║
║  └─ Last scan: 3 min ago                                 ║
║                                                          ║
║  📋 Jira Sprint: Sprint 24 (Day 7/14)                   ║
║  ├─ My tickets: 2 In Progress, 1 To Do, 3 Done          ║
║  ├─ Sprint health: ⚠️ slightly behind (68% SP remaining) ║
║  └─ Blockers: PROJ-123 blocks 2 teammates                ║
║                                                          ║
║  🔀 GitLab                                               ║
║  ├─ Active MRs: 3 (1 passed, 1 running, 1 failed)       ║
║  ├─ 🔄 Pipeline #78901: deploy_uat running               ║
║  └─ ❌ Pipeline #78850: test failed (MR !448)            ║
║                                                          ║
║  🖥️ Code Session                                         ║
║  └─ Active: fix/PROJ-123-login-bug (pipeline running)    ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝

Quick actions:
  /chat-reply     — Review pending chat replies
  /sprint-board   — Full sprint board view
  /pipeline-watch — Monitor active pipeline
  /code-session   — Start new coding session
```

### 4. Proactive Alerts

Flag items needing immediate attention:
- Urgent chat messages unread >30 min
- Pipeline failed with no retry attempted
- Sprint at risk (velocity below target)
- MR with all approvals but not merged
