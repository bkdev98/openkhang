---
name: chat-scan
description: >-
  Scan Google Chat for new messages. This skill should be invoked with
  "/chat-scan" to sync new messages via Matrix API (mautrix-googlechat bridge),
  categorize them, auto-reply to routine ones, and surface actionable items.
  Compatible with "/loop 5m /chat-scan" for continuous monitoring.
  Uses real-time sync — no polling delay.
argument-hint: "[--setup] [--dry-run] [--full-sync]"
allowed-tools: ["Bash", "Read", "Write", "Edit", "Agent"]
version: 1.0.0
---

# Chat Scan

Scan Google Chat for new messages via Matrix sync API — real-time, structured, reliable.

## Arguments

- `--setup` — Run first-time setup: verify bridge connection, build room map, extract tone
- `--dry-run` — Scan and categorize but don't send any auto-replies
- `--full-sync` — Force a full sync (ignore saved since_token), useful for rebuilding state

## Execution Flow

### 1. Load Config & State

Read environment variables from `.env`:
```bash
MATRIX_HOMESERVER=http://localhost:8008
MATRIX_ACCESS_TOKEN=syt_xxx
```

Read `.claude/gchat-autopilot.local.md` for:
- `room_map` — Matrix room ID → Google Chat space name mapping
- `monitored_rooms` — whitelist of rooms to monitor
- `tone_profile` — for reply drafting

If state file doesn't exist or `--setup` flag passed, run **First-Time Setup** (see below).

### 2. Get New Messages

**Option A — Read from inbox (preferred, when listener is running):**

Check if the listener daemon is running and `.claude/gchat-inbox.jsonl` has content:

```bash
INBOX=".claude/gchat-inbox.jsonl"
INBOX_TMP=".claude/gchat-inbox.processing.jsonl"
if [ -f "$INBOX" ] && [ -s "$INBOX" ]; then
  # Atomically swap the inbox to avoid losing messages the listener writes during processing
  mv "$INBOX" "$INBOX_TMP"
  # Read all messages from the swapped file
  MESSAGES=$(cat "$INBOX_TMP")
  # Clean up after processing
  rm -f "$INBOX_TMP"
fi
```

**Why atomic rename:** The listener daemon appends to the inbox concurrently. Using `> "$INBOX"` (truncate) is racy — messages written between `cat` and `>` would be lost. `mv` is atomic on the same filesystem, so the listener will create a fresh file on its next write.

Each line is a JSON object with: `room_id`, `room_name`, `sender`, `body`, `timestamp`, `event_id`, `thread_event_id`.

This is instant — messages are already waiting in the file, collected in real-time by the listener.

**Option B — Direct sync (fallback, when listener is not running):**

```bash
SINCE_TOKEN=$(cat .claude/gchat-sync-token.txt 2>/dev/null || echo "")
curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/sync?since=$SINCE_TOKEN&timeout=30000" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN"
```

The `timeout=30000` makes this a **long-poll** — the server holds the connection up to 30s and returns immediately when new events arrive.

**Option C — Full sync (`--full-sync`):**

Omit the `since` parameter to get all rooms and recent messages. Useful for rebuilding state.

For `--full-sync`, omit the `since` parameter to get all rooms and recent messages.

### 3. Parse Sync Response

From the sync response JSON, extract new messages:

```
response.rooms.join → for each room_id:
  .timeline.events → filter for type "m.room.message"
    → extract: sender, content.body, origin_server_ts, event_id
    → check content.m.relates_to for thread context
```

**Filter rules:**
- Skip events where sender matches your own puppet ID (your own messages)
- Skip rooms not in `monitored_rooms` (unless `monitored_rooms: all`)
- Skip `blacklisted_rooms` entirely (filtered at listener level — these never appear in inbox)
- For `mention_only_rooms`, only messages @mentioning you pass through (also filtered at listener level)
- Skip non-message events (state changes, reactions, etc. — unless actionable)
- Resolve room names from `room_map` (or from `state.events` with `m.room.name`)

**Save `next_batch`** from response as the new `matrix_since_token` in state file.

### 4. Build Message List

For each new message, construct:

```
- room_id: "!abc:localhost"
- room_name: "[QLCT] The worker" (from room_map)
- sender: "NGUYỄN THỊ QUỲNH NHƯ" (display name of bridged user)
- message: "EXPENSE-4448 [APP] Thêm CTA nhập giao dịch"
- timestamp: "2026-03-25T11:40:00+07:00" (from origin_server_ts)
- event_id: "$eventXYZ"
- thread_event_id: "$threadRoot" or null
- is_dm: true/false (based on room type)
```

### 5. Categorize Messages

Spawn the `chat-categorizer` agent with the batch of new messages and the tone profile from state. The agent returns categorized messages with draft replies.

### 6. Execute Actions

For each categorized message:

- **FYI / Social** (auto-reply enabled, unless `--dry-run`):
  ```bash
  # URL-encode room ID (contains ! and :)
  ENC_ROOM=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$ROOM_ID'))")
  TXN_ID=$(date +%s%N)

  # Simple reply
  curl -s -X PUT "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/send/m.room.message/$TXN_ID" \
    -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"msgtype":"m.text","body":"Noted nha, cảm ơn!"}'

  # Thread reply (if message is in a thread)
  curl -s -X PUT "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/send/m.room.message/$TXN_ID" \
    -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"msgtype":"m.text","body":"Noted nha!","m.relates_to":{"rel_type":"m.thread","event_id":"$THREAD_ROOT"}}'

  # Emoji reaction (for social/emoji-only messages)
  curl -s -X PUT "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/send/m.reaction/$TXN_ID" \
    -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"m.relates_to":{"rel_type":"m.annotation","event_id":"$EVENT_ID","key":"👍"}}'
  ```

- **Urgent / Action Needed**: Add to `pending_drafts` in state file with:
  - room_id, event_id, thread_event_id, sender, message_preview, category, draft_reply, timestamp

If `--dry-run`, skip sending and just display the categorization results.

### 7. Update State

Update `.claude/gchat-autopilot.local.md`:
- `matrix_since_token` — new sync token
- `pending_drafts` — any new drafts added
- `room_map` — any new rooms discovered in this sync

### 8. Display Summary

```
📬 Chat Scan Complete — 12 new messages (synced in 0.3s)

🔴 Urgent (1):
  • [Happy User] NGÔ THỊ HỒNG THẢO: "Giao dịch bị treo, cần chuyển tiền gấp"
    → Draft: "Đang check rồi nha"

🟡 Action Needed (3):
  • [DM] PHAN THÙY DƯƠNG: "card VR-198 sao r a"
    → Draft: "Để em check lại nha"
  • [Redeem-promotion] PHAN THÙY DƯƠNG: "@BÙI QUỐC KHÁNH discuss with BE về VR-209"
    → Draft: "Ok em, em check rồi reply nha"
  • [ACB After Payment] NGUYỄN NGỌC HẢI: "@tất cả AI Productivity mục tiêu"
    → Draft: "Noted anh, em xem qua rồi discuss chiều nha"

🟢 Auto-replied (6):
  • [Group Cơm] PHẠM THỊ HỒNG ĐÀO: "Hàng có sẵn" → 👍
  • [Trackify] NGUYỄN THANH HẢI: "Release note E2E Duration" → "Noted, cảm ơn!"
  ...

⚪ Skipped (2): bot messages, non-monitored rooms
```

## First-Time Setup

When no state file exists or `--setup` is passed:

### Prerequisites Check
1. Verify bridge is running: `docker compose -f ~/.mautrix-googlechat/docker-compose.yml ps`
2. Verify Matrix access: `curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/account/whoami" -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN"`
3. If bridge not set up: direct user to `references/mautrix-setup.md`

### Build Room Map
1. `curl` the `/joined_rooms` endpoint to list all bridged rooms
2. For each room, `curl` `/rooms/$ROOM_ID/state/m.room.name` to get the Google Chat space name
3. Build the `room_map` dictionary: `room_id → space_name`
4. Identify DMs (rooms with only 2 members — you and one puppet user)

### Learn Tone
1. Pick 3-4 active rooms from the room map
2. Fetch recent messages: `curl` `/rooms/$ROOM_ID/messages?dir=b&limit=50`
3. Filter for messages from your own puppet (sender matches your Google Chat puppet ID)
4. Extract language, formality, common phrases, avg length

### Create State File
Write `.claude/gchat-autopilot.local.md` with:
- account, matrix_since_token, room_map, monitored_rooms, tone_profile

### Confirm
Show extracted tone profile and room list, ask user to confirm or adjust.

## Error Handling

- If Matrix homeserver unreachable: check Docker containers are running
- If 401 Unauthorized: access token expired, re-login and update `.env`
- If sync returns empty rooms: bridge may be disconnecting, check bridge logs
- If bridge disconnected from Google Chat: cookies expired, re-authenticate (see setup guide)
- If a room is missing from room_map: run `--full-sync` to rebuild
