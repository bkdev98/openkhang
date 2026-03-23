---
name: chat-spaces
description: >-
  This skill should be invoked with "/chat-spaces" to list and manage
  which Google Chat spaces and DMs the autopilot monitors. Use to view
  current spaces, add or remove spaces from monitoring, or refresh the
  spaces list.
argument-hint: "[list|add|remove|refresh]"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
version: 0.1.0
---

# Chat Spaces

Manage monitored Google Chat spaces for the autopilot.

## Subcommands

### list (default)

Display all spaces and their monitoring status:

```bash
gog chat spaces ls -a ACCOUNT -j --results-only
```

Output format:
```
📋 Google Chat Spaces (12 total, monitoring: all)

DMs:
  ✅ Alice Chen (spaces/AAAA) — last scan: 2 min ago
  ✅ Bob Kim (spaces/BBBB) — last scan: 2 min ago
  ...

Groups:
  ✅ #backend (spaces/CCCC) — last scan: 2 min ago
  ✅ #general (spaces/DDDD) — last scan: 2 min ago
  ...
```

### add <space-id|space-name>

Add a specific space to the monitoring list. Only relevant when `monitored_spaces` is a whitelist (not "all").

### remove <space-id|space-name>

Remove a space from monitoring. Switch from "all" to explicit whitelist if needed, excluding the removed space.

### refresh

Re-fetch the spaces list from Google Chat and update the state file. Useful when new DMs or group spaces are created.

## State Management

Read and update `monitored_spaces` in `.claude/gchat-autopilot.local.md`.

- `monitored_spaces: all` — monitor everything (default)
- `monitored_spaces: [spaces/AAAA, spaces/CCCC]` — whitelist mode
