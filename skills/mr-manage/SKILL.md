---
name: mr-manage
description: >-
  This skill should be invoked with "/mr-manage" to manage GitLab merge
  requests — list, view, approve, merge, or comment on MRs. Provides
  a quick overview of MR status and pipeline health.
argument-hint: "[list|view|approve|merge|comment] [MR_ID]"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
version: 0.1.0
---

# MR Manage

Manage GitLab merge requests.

## Subcommands

### list (default)

```bash
glab mr list --assignee=@me --json
```

Display:
```
📋 My Merge Requests (3)

 #   │ Title                              │ Pipeline │ Reviews │ Age
─────┼────────────────────────────────────┼──────────┼─────────┼────────
 !456│ fix(PROJ-123): Fix login bug       │ ✅ passed│ 1/2     │ 2h
 !452│ feat(PROJ-100): Payment API        │ 🔄 run   │ 0/2     │ 1d
 !448│ refactor: Clean up auth middleware │ ❌ failed│ 2/2     │ 3d
```

### view <MR_ID>

```bash
glab mr view MR_ID --json
```

Show: title, description, diff stats, pipeline status, review status, comments.

### approve <MR_ID>

```bash
glab mr approve MR_ID
```

### merge <MR_ID>

```bash
glab mr merge MR_ID --squash --remove-source-branch
```

Pre-checks: pipeline passed, required approvals met.

### comment <MR_ID> <message>

```bash
glab mr note MR_ID --message "Comment text"
```
