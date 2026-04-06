#!/bin/bash
# Setup the mautrix-googlechat bridge infrastructure (Synapse + PostgreSQL + bridge)
# Usage: ./scripts/setup-bridge.sh [--reset]
#   --reset  Tear down existing containers and data, start fresh
set -euo pipefail

BRIDGE_DIR="$HOME/.mautrix-googlechat"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[setup]${NC} $*"; }
error() { echo -e "${RED}[setup]${NC} $*" >&2; }

# --- Pre-flight checks ---

if ! command -v docker &>/dev/null; then
  error "Docker is not installed. Install Docker Desktop first."
  exit 1
fi

if ! docker info &>/dev/null; then
  error "Docker daemon is not running. Start Docker Desktop first."
  exit 1
fi

if ! command -v jq &>/dev/null; then
  error "jq is not installed. Install with: brew install jq"
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  error "python3 is not installed."
  exit 1
fi

# --- Handle --reset ---

if [[ "${1:-}" == "--reset" ]]; then
  warn "Resetting: tearing down existing bridge infrastructure..."
  if [ -d "$BRIDGE_DIR" ]; then
    cd "$BRIDGE_DIR"
    docker compose down -v 2>/dev/null || true
    cd /
    rm -rf "$BRIDGE_DIR"
    info "Removed $BRIDGE_DIR"
  fi
  # Remove bridge-related env vars
  if [ -f "$ENV_FILE" ]; then
    sed -i '' '/^MATRIX_HOMESERVER=/d; /^MATRIX_ACCESS_TOKEN=/d' "$ENV_FILE" 2>/dev/null || true
  fi
  info "Reset complete. Re-run without --reset to set up fresh."
  exit 0
fi

# --- Check if already set up ---

if [ -d "$BRIDGE_DIR" ]; then
  cd "$BRIDGE_DIR"
  RUNNING=$(docker compose ps --format '{{.Name}}' 2>/dev/null | wc -l | tr -d ' ')
  if [ "$RUNNING" -ge 3 ]; then
    info "Bridge infrastructure already running ($RUNNING containers)."
    docker compose ps --format 'table {{.Name}}\t{{.Status}}'
    echo ""
    info "To tear down and start fresh: $0 --reset"
    exit 0
  fi
fi

# --- Step 1: Create directory ---

info "Creating bridge directory at $BRIDGE_DIR"
mkdir -p "$BRIDGE_DIR"
cd "$BRIDGE_DIR"

# --- Step 2: Write docker-compose.yml ---

if [ ! -f docker-compose.yml ]; then
  info "Writing docker-compose.yml"
  cat > docker-compose.yml << 'COMPOSE_EOF'
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
COMPOSE_EOF
else
  info "docker-compose.yml already exists, skipping"
fi

# --- Step 3: Initialize Synapse ---

if [ ! -f synapse-data/homeserver.yaml ]; then
  info "Generating Synapse config..."
  docker compose run --rm -e SYNAPSE_SERVER_NAME=localhost -e SYNAPSE_REPORT_STATS=no synapse generate
  info "Synapse config generated"

  # Patch homeserver.yaml to use PostgreSQL instead of SQLite
  info "Patching homeserver.yaml for PostgreSQL..."
  python3 << 'PYEOF'
import re
path = "synapse-data/homeserver.yaml"
with open(path) as f:
    content = f.read()

# Replace SQLite database config with PostgreSQL
sqlite_pattern = r'database:\n  name: sqlite3\n  args:\n    database: /data/homeserver\.db'
pg_replacement = """database:
  name: psycopg2
  args:
    user: synapse
    password: synapse
    database: synapse
    host: synapse-postgres
    port: 5432
    cp_min: 5
    cp_max: 10"""

content = re.sub(sqlite_pattern, pg_replacement, content)

# Enable registration
if 'enable_registration:' not in content:
    content += "\nenable_registration: true\nenable_registration_without_verification: true\n"

with open(path, 'w') as f:
    f.write(content)
print("homeserver.yaml patched")
PYEOF
else
  info "Synapse already initialized, skipping"
fi

# --- Step 4: Generate bridge config ---

if [ ! -f bridge-data/config.yaml ]; then
  info "Generating bridge config..."
  mkdir -p bridge-data
  docker compose run --rm googlechat-bridge python -m mautrix_googlechat -g
  info "Bridge config generated"

  # Patch bridge config using sed (no PyYAML dependency)
  info "Patching bridge config..."
  CONFIG="bridge-data/config.yaml"

  # Homeserver address (internal Docker network)
  sed -i '' 's|address: https\?://.*:8008|address: http://synapse:8008|' "$CONFIG"
  sed -i '' 's|domain: .*|domain: localhost|' "$CONFIG"

  # Appservice database — replace SQLite with PostgreSQL
  sed -i '' 's|database: sqlite:.*|database: postgres://mautrix:mautrix@bridge-postgres/googlechat|' "$CONFIG"

  # Bridge permissions — set Claude as admin
  # Replace the existing permissions block
  python3 << 'PYEOF'
import re
path = "bridge-data/config.yaml"
with open(path) as f:
    content = f.read()

# Replace permissions block
content = re.sub(
    r'(    permissions:\n)((?:        .*\n)*)',
    r'\1        "*": user\n        "@claude:localhost": admin\n',
    content
)

# Set initial_chat_sync
content = re.sub(r'initial_chat_sync: \d+', 'initial_chat_sync: 50', content)

with open(path, 'w') as f:
    f.write(content)
print("bridge config patched")
PYEOF

  # Copy registration to Synapse
  if [ -f bridge-data/registration.yaml ]; then
    cp bridge-data/registration.yaml synapse-data/googlechat-registration.yaml
    info "Copied registration.yaml to synapse-data/"

    # Add appservice config to homeserver.yaml if not present
    if ! grep -q 'app_service_config_files' synapse-data/homeserver.yaml; then
      echo "" >> synapse-data/homeserver.yaml
      echo "app_service_config_files:" >> synapse-data/homeserver.yaml
      echo "  - /data/googlechat-registration.yaml" >> synapse-data/homeserver.yaml
      info "Added appservice registration to homeserver.yaml"
    fi
  else
    error "registration.yaml not found in bridge-data/"
    exit 1
  fi
else
  info "Bridge config already exists, skipping"
fi

# --- Step 5: Start Synapse + databases ---

info "Starting Synapse and databases..."
docker compose up -d synapse synapse-postgres bridge-postgres

info "Waiting for Synapse to be ready..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8008/_matrix/client/v3/login >/dev/null 2>&1; then
    info "Synapse is ready"
    break
  fi
  if [ "$i" -eq 30 ]; then
    error "Synapse failed to start within 60s. Check: docker compose logs synapse"
    exit 1
  fi
  sleep 2
done

# --- Step 6: Create Claude user ---

# Check if user already exists by trying to login
EXISTING_TOKEN=$(curl -sf -X POST http://localhost:8008/_matrix/client/v3/login \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","user":"claude","password":"claude-bot-pass"}' 2>/dev/null \
  | jq -r '.access_token // empty' 2>/dev/null || true)

if [ -n "$EXISTING_TOKEN" ]; then
  info "Claude user already exists, got access token"
  ACCESS_TOKEN="$EXISTING_TOKEN"
else
  info "Registering Claude user..."
  docker compose exec -T synapse register_new_matrix_user \
    -u claude -p claude-bot-pass \
    -a -c /data/homeserver.yaml http://localhost:8008

  ACCESS_TOKEN=$(curl -s -X POST http://localhost:8008/_matrix/client/v3/login \
    -H 'Content-Type: application/json' \
    -d '{"type":"m.login.password","user":"claude","password":"claude-bot-pass"}' \
    | jq -r '.access_token')

  if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
    error "Failed to get access token. Check Synapse logs."
    exit 1
  fi
  info "Claude user registered and logged in"
fi

# --- Step 7: Save to .env ---

info "Updating $ENV_FILE"
touch "$ENV_FILE"

# Update or add MATRIX_HOMESERVER
if grep -q '^MATRIX_HOMESERVER=' "$ENV_FILE"; then
  sed -i '' 's|^MATRIX_HOMESERVER=.*|MATRIX_HOMESERVER=http://localhost:8008|' "$ENV_FILE"
else
  echo "" >> "$ENV_FILE"
  echo "# --- Matrix / Google Chat bridge ---" >> "$ENV_FILE"
  echo "MATRIX_HOMESERVER=http://localhost:8008" >> "$ENV_FILE"
fi

# Update or add MATRIX_ACCESS_TOKEN
if grep -q '^MATRIX_ACCESS_TOKEN=' "$ENV_FILE"; then
  sed -i '' "s|^MATRIX_ACCESS_TOKEN=.*|MATRIX_ACCESS_TOKEN=$ACCESS_TOKEN|" "$ENV_FILE"
else
  echo "MATRIX_ACCESS_TOKEN=$ACCESS_TOKEN" >> "$ENV_FILE"
fi

# --- Step 8: Start full stack ---

info "Starting full stack (including bridge)..."
docker compose up -d

info "Waiting for all containers..."
sleep 5

# --- Step 9: Verify ---

info "Verifying setup..."
echo ""

WHOAMI=$(curl -s http://localhost:8008/_matrix/client/v3/account/whoami \
  -H "Authorization: Bearer $ACCESS_TOKEN" | jq -r '.user_id // "FAILED"')
echo "  Matrix user:  $WHOAMI"

CONTAINERS=$(docker compose ps --format '{{.Name}}: {{.Status}}' 2>/dev/null)
echo "  Containers:"
echo "$CONTAINERS" | sed 's/^/    /'

echo ""
info "Bridge infrastructure is ready!"
echo ""
echo "  Next steps:"
echo "    1. Run /chat-auth in Claude Code to authenticate with Google Chat cookies"
echo "    2. Run /chat-listen to start the real-time message listener"
echo "    3. Run /chat-scan to process incoming messages"
echo ""
