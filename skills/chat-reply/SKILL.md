---
name: chat-reply
description: >-
  This skill should be invoked with "/chat-reply" to review and send
  pending draft replies queued by chat-scan. Allows approving, editing,
  or rejecting each draft before sending via Google Chat.
argument-hint: "[--send-all] [--reject-all]"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
version: 0.1.0
---

# Chat Reply

Review and send pending draft replies from the autopilot queue.

## Arguments

- `--send-all` — Approve and send all pending drafts without review
- `--reject-all` — Clear all pending drafts without sending

## Execution Flow

### 1. Load Pending Drafts

Read `.claude/gchat-autopilot.local.md` and extract `pending_drafts` list.

If no pending drafts, display: "No pending replies. Run /chat-scan to check for new messages."

### 2. Present Drafts for Review

Display each draft with context:

```
📝 Pending Replies (3)

[1] 🔴 Urgent — DM with Alice (2 min ago)
    Message: "Server is returning 500s on /api/users"
    Draft:   "Looking into this now"
    → (a)pprove / (e)dit / (s)kip / (r)eject

[2] 🟡 Action — #backend, Bob (15 min ago)
    Message: "Can you review PR #142?"
    Draft:   "Will review shortly"
    → (a)pprove / (e)dit / (s)kip / (r)eject

[3] 🟡 Action — DM with Carol (1 hr ago)
    Message: "Need the API spec by Thursday"
    Draft:   "On it, will share tomorrow"
    → (a)pprove / (e)dit / (s)kip / (r)eject
```

### 3. Process User Decisions

For each draft, handle the user's choice:

- **Approve**: Send the draft reply via gogcli:
  ```bash
  gog chat messages send SPACE --text "REPLY" --thread THREAD -a ACCOUNT
  ```
  Remove from pending_drafts.

- **Edit**: Ask user for revised text, then send the edited version. Remove from pending_drafts.

- **Skip**: Leave in queue for next review cycle.

- **Reject**: Remove from pending_drafts without sending.

### 4. Update State

Write updated `pending_drafts` back to state file.

### 5. Summary

```
✅ Sent: 2 replies
⏭️ Skipped: 1 (still in queue)
🗑️ Rejected: 0

Next scan in ~5 min (if /loop active)
```

## Batch Mode

With `--send-all`: skip review, send all drafts, clear queue.
With `--reject-all`: skip review, clear all drafts without sending.

Both modes display a summary of what was sent/cleared.
