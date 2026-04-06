# mautrix-googlechat Bridge Setup

One-time infrastructure setup for real-time Google Chat access via Matrix protocol.

## Architecture

```
Google Chat ←→ mautrix-googlechat bridge ←→ Synapse (Matrix homeserver) ←→ Claude Code (Matrix API)
                      ↑                            ↑
                bridge-postgres              synapse-postgres
```

Each Google Chat space/DM becomes a Matrix room. Messages flow in real-time.

## Prerequisites

- Docker + Docker Compose v2
- A browser session logged into Google Chat (for cookie extraction)
- `jq` and `curl` for verification steps

## Quick Start (Automated)

```bash
cd /path/to/openkhang
./scripts/setup-bridge.sh
```

The script handles steps 1–7 below automatically. After it completes, run `/chat-auth` to authenticate with Google Chat cookies.

## Manual Setup Steps

### 1. Create the infrastructure directory

```bash
mkdir -p ~/.mautrix-googlechat && cd ~/.mautrix-googlechat
```

### 2. Docker Compose stack

Create `docker-compose.yml`:

```yaml
services:
  synapse:
    image: matrixdotorg/synapse:latest
    container_name: synapse
    restart: unless-stopped
    volumes:
      - ./synapse-data:/data
    ports:
      - "8008:8008"
    depends_on:
      synapse-postgres:
        condition: service_healthy

  synapse-postgres:
    image: postgres:16-alpine
    container_name: synapse-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: synapse
      POSTGRES_PASSWORD: synapse
      POSTGRES_DB: synapse
      POSTGRES_INITDB_ARGS: "--encoding=UTF8 --lc-collate=C --lc-ctype=C"
    volumes:
      - ./synapse-postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U synapse"]
      interval: 5s
      timeout: 5s
      retries: 5

  bridge-postgres:
    image: postgres:16-alpine
    container_name: bridge-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: mautrix
      POSTGRES_PASSWORD: mautrix
      POSTGRES_DB: googlechat
      POSTGRES_INITDB_ARGS: "--encoding=UTF8 --lc-collate=C --lc-ctype=C"
    volumes:
      - ./bridge-postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mautrix"]
      interval: 5s
      timeout: 5s
      retries: 5

  googlechat-bridge:
    image: dock.mau.dev/mautrix/googlechat:latest
    container_name: mautrix-googlechat
    restart: unless-stopped
    dns:
      - 8.8.8.8
      - 8.8.4.4
    depends_on:
      synapse:
        condition: service_started
      bridge-postgres:
        condition: service_healthy
    volumes:
      - ./bridge-data:/data
```

**Key differences from the simple single-postgres setup:**
- Separate databases for Synapse and the bridge (avoids contention)
- Healthchecks on Postgres so services wait for readiness before starting
- DNS override on the bridge (some corporate networks block Google Chat API via internal DNS)

### 3. Initialize Synapse

```bash
docker compose run --rm synapse generate
```

Edit `synapse-data/homeserver.yaml` — set the database to use PostgreSQL:

```yaml
database:
  name: psycopg2
  args:
    user: synapse
    password: synapse
    database: synapse
    host: synapse-postgres
    port: 5432
    cp_min: 5
    cp_max: 10
```

Also enable registration (temporarily, for creating the Claude user):

```yaml
enable_registration: true
enable_registration_without_verification: true
```

### 4. Generate bridge config

```bash
docker compose run --rm googlechat-bridge python -m mautrix_googlechat -g
```

Edit `bridge-data/config.yaml`:

```yaml
homeserver:
  address: http://synapse:8008
  domain: localhost

appservice:
  address: http://googlechat-bridge:29320
  database: postgres://mautrix:mautrix@bridge-postgres/googlechat

bridge:
  username_template: "googlechat_{userid}"
  displayname_template: "{full_name} (Google Chat)"
  initial_chat_sync: 50
  permissions:
    "*": user
    "@claude:localhost": admin
```

Copy the generated `registration.yaml` to `synapse-data/` and reference it in `homeserver.yaml`:

```yaml
app_service_config_files:
  - /data/googlechat-registration.yaml
```

### 5. Create a Matrix user for Claude Code

```bash
# Start Synapse + databases first
docker compose up -d synapse synapse-postgres bridge-postgres

# Wait for Synapse to be ready
until curl -sf http://localhost:8008/_matrix/client/v3/login >/dev/null 2>&1; do sleep 2; done

# Register admin user
docker compose exec synapse register_new_matrix_user \
  -u claude -p claude-bot-pass \
  -a -c /data/homeserver.yaml http://localhost:8008
```

### 6. Get access token

```bash
ACCESS_TOKEN=$(curl -s -X POST http://localhost:8008/_matrix/client/v3/login \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","user":"claude","password":"claude-bot-pass"}' \
  | jq -r '.access_token')

echo "MATRIX_ACCESS_TOKEN=$ACCESS_TOKEN"
```

Add to the project `.env` file:

```bash
MATRIX_HOMESERVER=http://localhost:8008
MATRIX_ACCESS_TOKEN=<token from above>
```

### 7. Start the full stack

```bash
docker compose up -d
```

Verify all containers are healthy:

```bash
docker compose ps
# Expected: synapse (Up), synapse-postgres (Up, healthy),
#           bridge-postgres (Up, healthy), mautrix-googlechat (Up)
```

### 8. Authenticate with Google Chat

Run `/chat-auth` in Claude Code — it will guide you through cookie extraction and send them to the bridge automatically.

Or do it manually:

1. Open `https://chat.google.com` in a **private/incognito** window
2. Log in with your Google account
3. Open DevTools (F12) → Application → Cookies → `https://chat.google.com`
4. Copy these 5 cookie values: `COMPASS`, `SSID`, `SID`, `OSID`, `HSID`
5. **Close the incognito window immediately** after copying (prevents invalidation)

Create the bot room and send cookies via Matrix API:

```bash
# Create a DM with the bridge bot
BOT_ROOM=$(curl -s -X POST "http://localhost:8008/_matrix/client/v3/createRoom" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"invite":["@googlechatbot:localhost"],"is_direct":true}' | jq -r '.room_id')

# URL-encode the room ID (contains ! and :)
ENC_ROOM=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$BOT_ROOM'))")

# Send login command
curl -s -X PUT "http://localhost:8008/_matrix/client/v3/rooms/$ENC_ROOM/send/m.room.message/$(date +%s%N)" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"msgtype":"m.text","body":"login-cookie {\"compass\":\"...\",\"ssid\":\"...\",\"sid\":\"...\",\"osid\":\"...\",\"hsid\":\"...\"}"}'
```

The bridge will start syncing all your Google Chat spaces as Matrix rooms.

### 9. Verify

```bash
# Check auth
curl -s "http://localhost:8008/_matrix/client/v3/account/whoami" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" | jq .

# List joined rooms — should show bridged Google Chat spaces
curl -s "http://localhost:8008/_matrix/client/v3/joined_rooms" \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" | jq '.joined_rooms | length'
```

### 10. Start the message listener

```bash
cd /path/to/openkhang
python3 scripts/matrix-listener.py --daemon
```

Or run `/chat-listen` in Claude Code.

## Cookie Refresh

Cookies expire periodically (typically 1–2 weeks). When the bridge disconnects:

1. Run `/chat-auth` to re-authenticate
2. Or manually: re-extract cookies from a new incognito session and send `login-cookie {...}` to the bridge bot room

The bridge logs `Successfully logged in as NAME <email>` when successful.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Bridge won't start | `docker compose logs googlechat-bridge` — check for config errors |
| No rooms appearing | Wait 1–2 min after login; bridge syncs spaces gradually |
| Cookie expired | Run `/chat-auth` to re-authenticate with fresh cookies |
| Synapse won't start | Check `docker compose logs synapse` — verify registration.yaml path |
| Database connection error | `docker compose ps` — ensure postgres containers are healthy |
| Bridge can't reach Google | Check DNS; the compose file uses `8.8.8.8` to bypass corporate DNS |
| `register_new_matrix_user` fails | Ensure `enable_registration: true` in homeserver.yaml |
| Listener not receiving messages | Check `cat .claude/matrix-listener.log` for sync errors |
