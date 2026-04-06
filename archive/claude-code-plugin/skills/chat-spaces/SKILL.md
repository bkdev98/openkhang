---
name: chat-spaces
description: >-
  This skill should be invoked with "/chat-spaces" to list and manage
  which Google Chat spaces and DMs the autopilot monitors. Reads rooms
  from the Matrix homeserver (bridged from Google Chat via mautrix).
argument-hint: "[list|add|remove|blacklist|mention-only|refresh]"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
version: 1.0.0
---

# Chat Spaces

Manage monitored Google Chat spaces for the autopilot via Matrix API.

## Subcommands

### list (default)

List all bridged rooms from the Matrix homeserver with monitoring status.

```bash
# Get all joined rooms
ROOMS=$(curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/joined_rooms" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" | jq -r '.joined_rooms[]')

# For each room, get name and member count (URL-encode room IDs — they contain ! and :)
for ROOM_ID in $ROOMS; do
  ENC_ROOM=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$ROOM_ID'))")
  NAME=$(curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/state/m.room.name" \
    -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" | jq -r '.name // "DM"')
  echo "$ROOM_ID → $NAME"
done
```

Cross-reference with `monitored_rooms` in state file to show status.

Output format:
```
📋 Google Chat Spaces (42 rooms bridged, monitoring: 25)

DMs:
  ✅ PHAN THÙY DƯƠNG (!abc:localhost) — monitored
  ✅ NGUYỄN NGỌC HẢI (!def:localhost) — monitored
  ❌ CIO Buddy (!ghi:localhost) — not monitored
  ...

Spaces:
  ✅ [QLCT] The worker (!jkl:localhost) — monitored
  ✅ [Redeem-promotion] PO-Dev-Qc (!mno:localhost) — monitored
  🔇 Group Cơm (!pqr:localhost) — blacklisted
  👁️ [ABC] [Tech] MoMo App Platform (!stu:localhost) — mention-only
  ...

Bridge bot room:
  ⚙️ googlechatbot (!zzz:localhost) — system (always excluded)
```

### add <room-name|room-id>

Add a room to the monitoring list.

1. Search `room_map` for matching name (fuzzy match)
2. Add the room_id to `monitored_rooms` in state file

### remove <room-name|room-id>

Remove a room from monitoring.

1. Find matching room_id
2. If `monitored_rooms: all`, switch to explicit list excluding the removed room
3. Update state file

### blacklist <room-name|room-id>

Completely ignore a room — no messages will be collected from it.

1. Search `room_map` for matching name (fuzzy match)
2. Add the room_id to `blacklisted_rooms` in state file
3. Restart the listener to apply: `python3 scripts/matrix-listener.py --stop && python3 scripts/matrix-listener.py --daemon`

To undo: edit `.claude/gchat-autopilot.local.md` and remove the room from `blacklisted_rooms`, then restart the listener.

### mention-only <room-name|room-id>

Only collect messages that @mention you in a room. Useful for high-volume spaces where you only care about directed messages.

1. Search `room_map` for matching name (fuzzy match)
2. Add the room_id to `mention_only_rooms` in state file
3. Restart the listener to apply

Mention detection checks for:
- Your Matrix puppet ID (`@googlechat_YOURID:localhost`) in formatted_body
- Your email username in the message body
- Matrix `matrix.to` links pointing to your puppet (how Google Chat @-mentions are bridged)

To undo: remove the room from `mention_only_rooms` and restart the listener.

### refresh

Re-sync the room map from Matrix.

1. Fetch `/joined_rooms`
2. For each room, fetch room name
3. Compare with existing `room_map`, report new/removed rooms
4. Update `room_map` in state file

Useful when new Google Chat spaces are created — the bridge auto-joins them, but the room map needs updating.

## State Management

Read and update room filtering in `.claude/gchat-autopilot.local.md`.

- `monitored_rooms: all` — monitor all bridged rooms (default)
- `monitored_rooms: ["!abc:localhost", "!def:localhost"]` — whitelist mode
- `blacklisted_rooms:` — list of room IDs to completely ignore (no messages collected)
- `mention_only_rooms:` — list of room IDs where only @mentions are collected

Filtering is applied at the listener level (`scripts/matrix-listener.py`), so changes require a listener restart to take effect.

## Identifying DMs vs Spaces

- **DMs**: Rooms with exactly 2 members (you + one puppet), `is_direct: true` in room state
- **Spaces**: Rooms with 3+ members, have a group-style name
- **Bridge bot room**: Room with `@googlechatbot:localhost` — always exclude from monitoring

## Room Discovery

When the bridge syncs a new Google Chat space, it auto-creates a Matrix room and invites you. New rooms appear in `/joined_rooms` after the next sync. Run `/chat-spaces refresh` to pick them up.
