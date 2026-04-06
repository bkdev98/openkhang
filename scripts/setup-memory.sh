#!/usr/bin/env bash
# setup-memory.sh — Bootstrap the openkhang memory layer
#
# Steps:
#   1. Start postgres, redis via docker compose
#   2. Wait for postgres to be healthy
#   3. Apply schema.sql (idempotent — uses IF NOT EXISTS)
#   4. Verify embedding API key is set
#   5. Test embedding endpoint responds
#   6. Print next-steps summary
#
# Usage: bash scripts/setup-memory.sh
# Run from project root.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

COMPOSE_FILE="docker-compose.yml"
PG_HOST="localhost"
PG_PORT="5433"
PG_USER="openkhang"
PG_DB="openkhang"

# ── Colour helpers ────────────────────────────────────────────────────
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
info()   { printf '  [info] %s\n' "$*"; }
step()   { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# ── Preflight checks ─────────────────────────────────────────────────
step "Preflight checks"

if ! command -v docker &>/dev/null; then
  red "docker is not installed or not on PATH"
  exit 1
fi

if ! docker info &>/dev/null; then
  red "Docker daemon is not running. Start Docker Desktop and retry."
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  red "docker-compose.yml not found at project root: $PROJECT_ROOT"
  exit 1
fi

info "Docker OK"
info "Compose file: $COMPOSE_FILE"

# ── Start services ───────────────────────────────────────────────────
step "Starting postgres, redis"
docker compose up -d postgres redis
info "Containers started (or already running)"

# ── Wait for Postgres ────────────────────────────────────────────────
step "Waiting for Postgres to be healthy"
RETRIES=30
until docker compose exec -T postgres pg_isready -U "$PG_USER" -d "$PG_DB" &>/dev/null; do
  RETRIES=$((RETRIES - 1))
  if [[ $RETRIES -le 0 ]]; then
    red "Postgres did not become healthy after 30 attempts"
    docker compose logs postgres | tail -20
    exit 1
  fi
  printf '.'
  sleep 2
done
echo ""
green "Postgres is ready"

# ── Apply schema ─────────────────────────────────────────────────────
step "Applying schema.sql"
docker compose exec -T postgres psql \
  -U "$PG_USER" \
  -d "$PG_DB" \
  -f /docker-entrypoint-initdb.d/01-schema.sql \
  && green "Schema applied" \
  || yellow "Schema apply returned non-zero (may already be initialised — check above output)"

# ── Check embedding API key ──────────────────────────────────────────
step "Checking embedding API configuration"

# Load .env if present
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

EMBEDDING_API_KEY="${EMBEDDING_API_KEY:-}"
EMBEDDING_API_URL="${EMBEDDING_API_URL:-https://openrouter.ai/api/v1}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-BAAI/bge-m3}"

if [[ -z "$EMBEDDING_API_KEY" ]]; then
  red "EMBEDDING_API_KEY is not set in .env"
  info "Get a key at https://openrouter.ai/keys and add to .env:"
  info "  EMBEDDING_API_KEY=sk-or-..."
  exit 1
fi
green "EMBEDDING_API_KEY is set"

# ── Verify embedding endpoint ────────────────────────────────────────
step "Verifying embedding endpoint ($EMBEDDING_MODEL via $EMBEDDING_API_URL)"
EMBED_RESPONSE=$(curl -sf "$EMBEDDING_API_URL/embeddings" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $EMBEDDING_API_KEY" \
  -d "{\"model\": \"$EMBEDDING_MODEL\", \"input\": \"hello world\"}" \
  || true)

if echo "$EMBED_RESPONSE" | grep -q '"embedding"'; then
  green "Embedding endpoint OK — $EMBEDDING_MODEL is responding"
else
  yellow "Embedding test returned unexpected response:"
  echo "$EMBED_RESPONSE"
  yellow "API key and URL are set but the endpoint may need verification."
fi

# ── Install Python deps ──────────────────────────────────────────────
step "Checking Python dependencies"
if [[ -f "services/requirements.txt" ]]; then
  if command -v pip3 &>/dev/null; then
    info "Installing services/requirements.txt into user site-packages"
    pip3 install --quiet -r services/requirements.txt
    green "Python dependencies installed"
  else
    yellow "pip3 not found — install manually: pip3 install -r services/requirements.txt"
  fi
fi

# ── Summary ──────────────────────────────────────────────────────────
step "Setup complete"
cat <<EOF

Services running:
  Postgres  → localhost:$PG_PORT  (db: $PG_DB, user: $PG_USER)
  Redis     → localhost:6379
  Embeddings → $EMBEDDING_API_URL  (model: $EMBEDDING_MODEL)

Next steps:
  1. Start Meridian: meridian (required for Mem0 memory extraction via Haiku)
  2. Ingest existing chat history:
       python3 services/memory/ingest-chat-history.py
  3. Run a quick smoke test:
       python3 - <<'PYEOF'
import asyncio
from services.memory import MemoryClient, MemoryConfig

async def test():
    config = MemoryConfig.from_env()
    client = MemoryClient(config)
    await client.connect()
    mid = await client.add_memory("Test memory — setup OK", {"source": "test"})
    results = await client.search("test")
    print(f"Memory ID: {mid}")
    print(f"Search returned {len(results)} result(s)")
    await client.close()

asyncio.run(test())
PYEOF

EOF
