---
name: chat-auth
description: >-
  Authenticate the mautrix-googlechat bridge with Google Chat cookies.
  Use "/chat-auth" when the bridge disconnects or on first setup.
  Guides user through cookie extraction from an incognito window
  and sends them to the bridge bot automatically.
argument-hint: "[--status] [--logout]"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
version: 1.0.0
---

# Chat Auth

Authenticate the mautrix-googlechat bridge with Google Chat.

## Arguments

- (no args) — Run the authentication flow
- `--status` — Check current bridge connection status
- `--logout` — Disconnect the bridge from Google Chat

## Status Check (`--status`)

```bash
# Check if bridge container is running
docker compose -f ~/.mautrix-googlechat/docker-compose.yml ps googlechat-bridge --format "{{.Status}}"

# Find the bridge bot room (room with @googlechatbot:localhost as a member)
# Look for it in joined rooms, or read from state file if available
BOT_ROOM=$(curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/joined_rooms" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" | python3 -c "
import json, sys, urllib.parse, urllib.request
data = json.load(sys.stdin)
hs = '$MATRIX_HOMESERVER'
token = '$MATRIX_ACCESS_TOKEN'
for rid in data['joined_rooms']:
    enc = urllib.parse.quote(rid)
    try:
        req = urllib.request.Request(f'{hs}/_matrix/client/v3/rooms/{enc}/members', headers={'Authorization': f'Bearer {token}'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            members = json.loads(resp.read())
            member_ids = [e['state_key'] for e in members.get('chunk', []) if e.get('content', {}).get('membership') == 'join']
            if '@googlechatbot:localhost' in member_ids and len(member_ids) == 2:
                print(rid)
                break
    except: pass
")

# Check bridge connection by reading the bot room for recent messages
ENC_BOT=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$BOT_ROOM'))")
curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_BOT/messages?dir=b&limit=3" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" | jq -r '.chunk[].content.body' | head -3
```

Look for "Successfully logged in" or "Logged out" messages from the bot.

Display status:
```
🟢 Bridge connected as BÙI QUỐC KHÁNH (khanh.bui2@mservice.com.vn)
   Uptime: 23 hours | Rooms: 30 | Session: active
```
or
```
🔴 Bridge disconnected — cookies expired
   Run /chat-auth to re-authenticate
```

## Authentication Flow (default)

### 1. Check Prerequisites

Verify Docker containers are running:
```bash
docker compose -f ~/.mautrix-googlechat/docker-compose.yml ps --format "{{.Name}}: {{.Status}}"
```

If not running, start them:
```bash
docker compose -f ~/.mautrix-googlechat/docker-compose.yml up -d
```

### 2. Guide User Through Cookie Extraction

Display these instructions to the user:

```
🔑 Google Chat Authentication

1. Open an INCOGNITO window in Chrome (Cmd+Shift+N)
2. Go to https://chat.google.com and log in
3. Once Chat loads, open DevTools (F12)
4. Go to Application tab → Storage → Cookies → https://chat.google.com
5. Copy these 5 cookie values:

   COMPASS  (long string, starts with "dynamite-")
   SSID     (short, ~17 chars)
   SID      (starts with "g.a000")
   OSID     (starts with "g.a000")
   HSID     (short, ~17 chars)

6. Paste the raw cookie table here (just select all rows and paste)
7. CLOSE THE INCOGNITO WINDOW IMMEDIATELY after pasting

⚠️  You MUST close the incognito window right after — keeping it open
    will cause Google to invalidate the session!
```

### 3. Parse Cookies from User Input

The user will paste either:
- Raw cookie table from Chrome DevTools (tab-separated rows with columns: Name, Value, Domain, Path, Expires, Size, etc.)
- JSON format: `{"compass":"...","ssid":"...","sid":"...","osid":"...","hsid":"..."}`
- Individual values

Parse the 5 required cookies from whatever format they provide:
- **COMPASS**: Look for the one with path `/` on domain `chat.google.com` (not the `/u/0/webchannel/` one)
- **SSID**: Short value, ~17 chars
- **SID**: Starts with `g.a000`, domain `.google.com`
- **OSID**: Starts with `g.a000`, domain `chat.google.com`
- **HSID**: Short value, ~17 chars

### 4. Send to Bridge

```bash
# Discover the bot room dynamically (same as --status check above)
# Or if already known, read from state. Then URL-encode:
ENC_BOT=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$BOT_ROOM'))")
TXN_ID=$(date +%s%N)

# Format and send login command
COOKIE_JSON='{"compass":"VALUE","ssid":"VALUE","sid":"VALUE","osid":"VALUE","hsid":"VALUE"}'

curl -s -X PUT "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_BOT/send/m.room.message/$TXN_ID" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"msgtype\":\"m.text\",\"body\":\"login-cookie $COOKIE_JSON\"}"
```

### 5. Verify Connection

Wait 10 seconds, then check the bot room for the bridge's response:

```bash
sleep 10
curl -s "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_BOT/messages?dir=b&limit=3" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" | jq -r '.chunk[].content.body'
```

Look for:
- ✅ `"Successfully logged in as NAME <email>"` — auth succeeded
- ❌ `"Those cookies don't seem to be valid"` — cookies invalid, retry

If successful, display:
```
✅ Bridge connected as BÙI QUỐC KHÁNH (khanh.bui2@mservice.com.vn)

Remember: Close the incognito window NOW if you haven't already!

The bridge will now sync your Google Chat spaces. This may take a few minutes
for the initial sync. Run /chat-spaces refresh to see bridged rooms.
```

### 6. Auto-Join New Rooms

After successful auth, join any new rooms the bridge creates:

```bash
# Get all rooms on server (admin API — @claude:localhost is admin)
ALL_ROOMS=$(curl -s "$MATRIX_HOMESERVER/_synapse/admin/v1/rooms?limit=500" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" | jq -r '.rooms[].room_id')

# Join each one
for ROOM_ID in $ALL_ROOMS; do
  ENC_ROOM=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$ROOM_ID'))")
  curl -s -X POST "$MATRIX_HOMESERVER/_matrix/client/v3/join/$ENC_ROOM" \
    -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
    -H "Content-Type: application/json" -d '{}' > /dev/null 2>&1
done
```

## Logout (`--logout`)

Send logout command to bridge bot:
```bash
ENC_BOT=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$BOT_ROOM'))")
TXN_ID=$(date +%s%N)
curl -s -X PUT "$MATRIX_HOMESERVER/_matrix/client/v3/rooms/$ENC_BOT/send/m.room.message/$TXN_ID" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"msgtype":"m.text","body":"logout"}'
```

## Cookie Parsing Reference

When user pastes raw Chrome DevTools cookie table, each row looks like:
```
COOKIE_NAME    cookie_value    .domain.com    /path    2027-...    size    flags...
```

Parse by splitting on tabs/whitespace, matching the 5 needed cookie names.
For COMPASS, there may be multiple entries — use the one with path `/` (not `/u/0/webchannel/`).
