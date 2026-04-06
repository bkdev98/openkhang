---
name: chat-reply
description: >-
  This skill should be invoked with "/chat-reply" to review and send
  pending draft replies queued by chat-scan. Sends replies via Matrix API
  which delivers them to Google Chat through the mautrix bridge.
argument-hint: "[--send-all] [--reject-all]"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
version: 1.0.0
---

# Chat Reply

Review and send pending draft replies from the autopilot queue via Matrix API.

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

[1] 🔴 Urgent — [Happy User] NGÔ THỊ HỒNG THẢO (16:37)
    Message: "Giao dịch bị treo, cần chuyển tiền gấp"
    Draft:   "Đang check rồi nha"
    → (a)pprove / (e)dit / (s)kip / (r)eject

[2] 🟡 Action — [DM] PHAN THÙY DƯƠNG (46 min ago)
    Message: "card VR-198 sao r a"
    Draft:   "Để em check lại nha"
    → (a)pprove / (e)dit / (s)kip / (r)eject

[3] 🟡 Action — [Redeem-promotion] PHAN THÙY DƯƠNG (14:05)
    Message: "@BÙI QUỐC KHÁNH discuss with BE"
    Draft:   "Ok em, em check rồi reply nha"
    → (a)pprove / (e)dit / (s)kip / (r)eject
```

### 3. Process User Decisions

For each draft, handle the user's choice:

- **Approve**: Send the reply via Matrix API (see Send Flow below). Remove from pending_drafts.

- **Edit**: Ask user for revised text, then send the edited version. Remove from pending_drafts.

- **Skip**: Leave in queue for next review cycle.

- **Reject**: Remove from pending_drafts without sending.

### 4. Send Flow (via Matrix API)

Load `MATRIX_HOMESERVER` and `MATRIX_ACCESS_TOKEN` from `.env`.

**URL-encode room IDs** (they contain `!` and `:`):
```bash
ENC_ROOM=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$ROOM_ID'))")
```

#### Simple reply (no thread):

```bash
TXN_ID=$(date +%s%N)
curl -s -X PUT \
  "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/send/m.room.message/$TXN_ID" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"msgtype\":\"m.text\",\"body\":\"$REPLY_TEXT\"}"
```

#### Thread reply:

```bash
TXN_ID=$(date +%s%N)
curl -s -X PUT \
  "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/send/m.room.message/$TXN_ID" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"msgtype\":\"m.text\",\"body\":\"$REPLY_TEXT\",\"m.relates_to\":{\"rel_type\":\"m.thread\",\"event_id\":\"$THREAD_EVENT_ID\"}}"
```

#### Emoji reaction:

```bash
TXN_ID=$(date +%s%N)
curl -s -X PUT \
  "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/send/m.reaction/$TXN_ID" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"m.relates_to\":{\"rel_type\":\"m.annotation\",\"event_id\":\"$EVENT_ID\",\"key\":\"$EMOJI\"}}"
```

#### Verify sent:

The Matrix API returns `{"event_id": "$newEventId"}` on success. Any non-200 response or missing `event_id` indicates failure.

### 5. Update State

Write updated `pending_drafts` back to `.claude/gchat-autopilot.local.md`.

### 6. Summary

```
✅ Sent: 2 replies
⏭️ Skipped: 1 (still in queue)
🗑️ Rejected: 0

Next scan in ~5 min (if /loop active)
```

## Batch Mode

With `--send-all`: skip review, send all drafts via Matrix API, clear queue.
With `--reject-all`: skip review, clear all drafts without sending.

Both modes display a summary of what was sent/cleared.

## Error Handling

- If Matrix homeserver unreachable: check Docker containers running
- If 401 Unauthorized: access token expired, re-login
- If send returns error: keep draft in queue, notify user with error details
- If bridge disconnected: replies queue in Matrix and deliver when bridge reconnects
