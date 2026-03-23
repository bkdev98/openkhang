---
name: chat-scan
description: >-
  Scan Google Chat for new messages. This skill should be invoked with
  "/chat-scan" to poll all monitored DMs and spaces for unread messages,
  categorize them, auto-reply to routine ones, and surface actionable items.
  Compatible with "/loop 5m /chat-scan" for continuous monitoring.
argument-hint: "[--setup] [--dry-run]"
allowed-tools: ["Bash", "Read", "Write", "Edit", "Agent"]
version: 0.1.0
---

# Chat Scan

Scan Google Chat for new messages, categorize them, and take action.

## Arguments

- `--setup` — Run first-time setup: prompt for account, fetch tone profile
- `--dry-run` — Scan and categorize but don't send any auto-replies

## Execution Flow

### 1. Load State

Read `.claude/gchat-autopilot.local.md` for account, last scan timestamps, and tone profile.

If state file doesn't exist or `--setup` flag passed, run **First-Time Setup** (see below).

### 2. Fetch Spaces

```bash
gog chat spaces ls -a ACCOUNT -j --results-only
```

Filter to DM spaces and spaces where user is a member.

### 3. Fetch New Messages Per Space

For each monitored space, fetch messages since last scan:

```bash
gog chat messages ls SPACE_NAME -a ACCOUNT -j --results-only
```

Filter out:
- Messages sent BY the user (sender matches account)
- Messages older than last scan timestamp for this space
- Bot/integration messages (unless they contain actionable content)

### 4. Categorize Messages

Spawn the `chat-categorizer` agent with the batch of new messages. The agent returns categorized messages with draft replies.

### 5. Execute Actions

For each categorized message:

- **FYI / Social** (auto-reply enabled): Send reply via `gog chat messages send`
  ```bash
  gog chat messages send SPACE --text "REPLY" --thread THREAD -a ACCOUNT
  ```
- **Urgent / Action Needed**: Add to pending_drafts in state file

If `--dry-run`, skip sending and just display the categorization results.

### 6. Update State

Update `last_scan` and per-space timestamps in state file.

### 7. Display Summary

Output a terminal-friendly summary:

```
📬 Chat Scan Complete — 12 new messages

🔴 Urgent (1):
  • [DM] Alice: "Server is returning 500s on /api/users" → Draft: "Looking into this now"

🟡 Action Needed (3):
  • [#backend] Bob: "Can you review PR #142?" → Draft: "Will review shortly"
  • [DM] Carol: "Need the API spec by Thursday" → Draft: "On it, will share tomorrow"
  • [#devops] Dave: "@quocs approve the deploy?" → Draft: "Checking now"

🟢 Auto-replied (6):
  • [#general] Eve: "Team standup notes attached" → "Noted, thanks!"
  • [DM] Frank: "Hey, good morning!" → "Morning! 👋"
  ...

⚪ Skipped (2): bot messages
```

## First-Time Setup

When no state file exists:

1. **Prompt for account email** — Ask user for their Google Workspace email
2. **List spaces** — Run `gog chat spaces ls` to verify access works
3. **Fetch tone profile** — Get 20 recent messages sent by user across spaces:
   ```bash
   gog chat messages ls SPACE -a ACCOUNT -j --results-only
   ```
   Filter to messages where sender matches account. Collect from multiple spaces.
4. **Analyze tone** — Extract language, formality, common phrases, avg length
5. **Create state file** — Write `.claude/gchat-autopilot.local.md` with initial config
6. **Confirm** — Show extracted tone profile and ask user to confirm or adjust

## Error Handling

- If `gog` command not found: instruct user to install gogcli
- If auth fails: instruct user to run `gog auth login`
- If a space fetch fails: log warning, continue with other spaces
- If rate limited: back off and report partial results
