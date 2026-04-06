#!/usr/bin/env bash
# setup-memory.sh — Bootstrap the openkhang memory layer
#
# Steps:
#   1. Start postgres, redis, ollama via docker compose
#   2. Wait for postgres to be healthy
#   3. Apply schema.sql (idempotent — uses IF NOT EXISTS)
#   4. Pull bge-m3 embedding model into Ollama
#   5. Verify Ollama embedding endpoint responds
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
OLLAMA_URL="http://localhost:11434"
EMBEDDING_MODEL="bge-m3"

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
# Schema is mounted as an init script so it runs automatically on first
# container start. We also apply it explicitly here to handle the case
# where the volume already existed without the schema.
docker compose exec -T postgres psql \
  -U "$PG_USER" \
  -d "$PG_DB" \
  -f /docker-entrypoint-initdb.d/01-schema.sql \
  && green "Schema applied" \
  || yellow "Schema apply returned non-zero (may already be initialised — check above output)"

# ── Start Ollama (native macOS) ──────────────────────────────────────
step "Checking Ollama (native)"

if ! command -v ollama &>/dev/null; then
  red "ollama not found. Install with: brew install ollama"
  exit 1
fi

# Start Ollama if not already running
if ! curl -sf "$OLLAMA_URL/api/tags" &>/dev/null; then
  info "Starting Ollama in background..."
  ollama serve &>/dev/null &
  OLLAMA_RETRIES=15
  until curl -sf "$OLLAMA_URL/api/tags" &>/dev/null; do
    OLLAMA_RETRIES=$((OLLAMA_RETRIES - 1))
    if [[ $OLLAMA_RETRIES -le 0 ]]; then
      red "Ollama did not start at $OLLAMA_URL after 15 attempts"
      red "Try manually: ollama serve"
      exit 1
    fi
    printf '.'
    sleep 2
  done
  echo ""
fi
green "Ollama is running"

# Pull embedding model
step "Pulling $EMBEDDING_MODEL embedding model"
info "This may take several minutes on first run (~600 MB download)"
ollama pull "$EMBEDDING_MODEL"
green "Model $EMBEDDING_MODEL pulled"

# ── Verify embedding endpoint ────────────────────────────────────────
step "Verifying embedding endpoint"
EMBED_RESPONSE=$(curl -sf "$OLLAMA_URL/api/embed" \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"$EMBEDDING_MODEL\", \"input\": \"hello world\"}" \
  || true)

if echo "$EMBED_RESPONSE" | grep -q '"embeddings"'; then
  green "Embedding endpoint OK — $EMBEDDING_MODEL is responding"
else
  yellow "Embedding test returned unexpected response:"
  echo "$EMBED_RESPONSE"
  yellow "Services are up but you may need to retry the embedding check manually."
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
  Ollama    → $OLLAMA_URL  (model: $EMBEDDING_MODEL)

Next steps:
  1. Add ANTHROPIC_API_KEY to your .env file (required for Mem0 LLM extraction)
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
