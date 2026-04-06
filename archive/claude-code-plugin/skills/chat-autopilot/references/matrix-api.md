# Matrix API Patterns for Google Chat Bridge

All Google Chat interactions go through the Matrix client API on Synapse. The bridge translates between Matrix events and Google Chat messages transparently.

## Config

```bash
# From .env
MATRIX_HOMESERVER=http://localhost:8008
MATRIX_ACCESS_TOKEN=syt_xxx
MATRIX_USER=@claude:localhost
```

All API calls use:
```bash
curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/ENDPOINT" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json"
```

## Core API Patterns

### Sync (get new messages — the primary polling endpoint)

```bash
# Initial sync (first run, gets all rooms + recent messages)
curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/sync?timeout=30000" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN"

# Incremental sync (subsequent runs, only new events since last sync)
curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/sync?since=$SINCE_TOKEN&timeout=30000" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN"
```

**Key:** The `timeout` parameter (ms) makes this a long-poll — the server holds the connection until new events arrive or timeout. This gives near-real-time delivery without aggressive polling.

**Response structure:**
```json
{
  "next_batch": "s12345_67890",  // ← save this as SINCE_TOKEN for next sync
  "rooms": {
    "join": {
      "!roomId:localhost": {
        "timeline": {
          "events": [
            {
              "type": "m.room.message",
              "sender": "@googlechat_USER:localhost",  // bridged Google Chat user
              "content": {
                "msgtype": "m.text",
                "body": "Hey, can you review PR #142?",
                "format": "org.matrix.custom.html",
                "formatted_body": "<p>Hey, can you review PR #142?</p>"
              },
              "event_id": "$eventId",
              "origin_server_ts": 1711368000000
            }
          ]
        },
        "state": {
          "events": [
            {
              "type": "m.room.name",
              "content": { "name": "[Redeem-promotion] PO-Dev-Qc" }
            }
          ]
        }
      }
    }
  }
}
```

### List Joined Rooms

```bash
curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/joined_rooms" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN"
```

Returns: `{"joined_rooms": ["!abc:localhost", "!def:localhost", ...]}`

### URL-Encoding Room IDs

Room IDs contain `!` and `:` (e.g. `!abc:localhost`) which must be URL-encoded in path segments. Use this helper:

```bash
ENC_ROOM=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$ROOM_ID'))")
```

All examples below use `$ENC_ROOM` for the encoded room ID.

### Get Room Name/Details

```bash
ENC_ROOM=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$ROOM_ID'))")
curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/state/m.room.name" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN"
```

Returns: `{"name": "[QLCT] The worker"}`

### Get Room Members (to identify who's in a space)

```bash
curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/members" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN"
```

### Fetch Message History (paginated)

```bash
curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/messages?dir=b&limit=20" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN"
```

### Send a Message

```bash
TXN_ID=$(date +%s%N)
curl -s -X PUT \
  "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/send/m.room.message/$TXN_ID" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"msgtype":"m.text","body":"Ok em, em check rồi reply nha"}'
```

### Send a Reaction (emoji)

```bash
TXN_ID=$(date +%s%N)
curl -s -X PUT \
  "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/send/m.reaction/$TXN_ID" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"m.relates_to":{"rel_type":"m.annotation","event_id":"$TARGET_EVENT_ID","key":"👍"}}'
```

### Reply in Thread

```bash
TXN_ID=$(date +%s%N)
curl -s -X PUT \
  "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/send/m.room.message/$TXN_ID" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "msgtype": "m.text",
    "body": "Noted nha, cảm ơn!",
    "m.relates_to": {
      "rel_type": "m.thread",
      "event_id": "$THREAD_ROOT_EVENT_ID"
    }
  }'
```

### Mark Room as Read

```bash
curl -s -X POST \
  "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_ROOM/receipt/m.read/$EVENT_ID" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN"
```

## Bridged User Format

The bridge creates puppet Matrix users for each Google Chat user:
- Format: `@googlechat_USERID:localhost`
- Display name: mirrors Google Chat name (e.g., "PHAN THÙY DƯƠNG")
- The user's own Google Chat account is bridged as `@googlechat_YOURID:localhost`

## Room ↔ Space Mapping

Each Google Chat space/DM becomes a Matrix room:
- Room name = Google Chat space name
- Room topic may contain the Google Chat space ID
- DMs are 1:1 Matrix rooms with `is_direct: true`

To build a mapping, iterate joined rooms and read their names:
```bash
for room in $(curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/joined_rooms" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" | jq -r '.joined_rooms[]'); do
  enc=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$room'))")
  name=$(curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$enc/state/m.room.name" \
    -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" 2>/dev/null | jq -r '.name // empty')
  echo "$room → $name"
done
```

## Sync Token Management

The `next_batch` token from each sync response must be saved to avoid re-processing messages:
- Store in `.claude/gchat-autopilot.local.md` as `matrix_since_token`
- On first run (no token), do an initial sync to get all rooms, then save the token
- On subsequent runs, use the saved token for incremental sync

## Tips

1. **Use `timeout=30000`** on sync for efficient long-polling (30s timeout)
2. **Filter sync** to reduce payload: `filter={"room":{"timeline":{"limit":50}}}`
3. **Batch room name lookups** on first run, cache in state file
4. **Skip events from your own puppet** (`sender` contains your Google Chat user ID)
5. **`origin_server_ts`** is Unix timestamp in milliseconds — use for time filtering
