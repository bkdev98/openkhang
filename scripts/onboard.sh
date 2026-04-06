#!/usr/bin/env bash
# onboard.sh — First-time setup for openkhang digital twin
#
# Steps:
#   1. Check prerequisites (Docker, Python)
#   2. Set up .env if missing
#   3. Set up Python venv + deps
#   4. Start infrastructure (Postgres, Redis)
#   5. Verify embedding API key
#   6. Check Matrix bridge
#   7. Initial data check
#   8. Print summary
#
# Usage: bash scripts/onboard.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

step()  { printf '\n%b==> %s%b\n' "$BOLD" "$*" "$NC"; }
info()  { printf '  %b[info]%b %s\n' "$CYAN" "$NC" "$*"; }
ok()    { printf '  %b[ok]%b %s\n' "$GREEN" "$NC" "$*"; }
warn()  { printf '  %b[warn]%b %s\n' "$YELLOW" "$NC" "$*"; }
fail()  { printf '  %b[fail]%b %s\n' "$RED" "$NC" "$*"; }

# ── 1. Prerequisites ─────────────────────────────────────────────
step "Checking prerequisites"

MISSING=0
for cmd in docker python3; do
    if command -v "$cmd" &>/dev/null; then
        ok "$cmd found"
    else
        fail "$cmd not found"
        MISSING=$((MISSING + 1))
    fi
done

# Optional CLIs
for cmd in jira glab; do
    if command -v "$cmd" &>/dev/null; then
        ok "$cmd found (optional)"
    else
        warn "$cmd not found — ${cmd} ingestion will be skipped"
    fi
done

if [[ $MISSING -gt 0 ]]; then
    fail "Missing required tools. Install them and re-run."
    exit 1
fi

# ── 2. Environment ───────────────────────────────────────────────
step "Checking environment"

if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        cp .env.example .env
        warn ".env created from .env.example — edit it with your API keys"
        info "Required: EMBEDDING_API_KEY (get at https://openrouter.ai/keys)"
        info "Required: GEMINI_API_KEY (for Mem0 memory extraction)"
        read -rp "  Press Enter to continue after editing .env (or Ctrl+C to abort)... "
    else
        fail ".env.example not found"
        exit 1
    fi
fi

# Load .env for checks
set -a; source .env 2>/dev/null || true; set +a

# Check critical env vars
if [[ -n "${EMBEDDING_API_KEY:-}" ]]; then
    ok "EMBEDDING_API_KEY is set"
else
    fail "EMBEDDING_API_KEY is not set — embeddings will not work"
    info "Get a key at https://openrouter.ai/keys and add to .env"
    exit 1
fi

if [[ -n "${GEMINI_API_KEY:-}" ]]; then
    ok "GEMINI_API_KEY is set"
else
    warn "GEMINI_API_KEY not set — Mem0 memory extraction will fail"
fi

# ── 3. Python venv ───────────────────────────────────────────────
step "Setting up Python environment"

if [[ ! -d services/.venv ]]; then
    info "Creating virtual environment..."
    python3 -m venv services/.venv
fi

info "Installing dependencies..."
services/.venv/bin/pip install -q -r services/requirements.txt 2>&1 | tail -1
ok "Python dependencies installed"

# ── 4. Infrastructure ────────────────────────────────────────────
step "Starting infrastructure (Postgres + Redis)"

if ! docker info &>/dev/null; then
    fail "Docker daemon not running. Start Docker Desktop first."
    exit 1
fi

docker compose up -d postgres redis
info "Waiting for Postgres..."
for i in $(seq 1 20); do
    if docker compose exec -T postgres pg_isready -U openkhang -d openkhang &>/dev/null; then
        break
    fi
    sleep 2
done
ok "Postgres ready"

# Apply schema
docker compose exec -T postgres psql -U openkhang -d openkhang \
    -f /docker-entrypoint-initdb.d/01-schema.sql &>/dev/null
ok "Schema applied"

# ── 5. Verify embedding API ─────────────────────────────────────
step "Verifying embedding API"

EMBEDDING_API_URL="${EMBEDDING_API_URL:-https://openrouter.ai/api/v1}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-BAAI/bge-m3}"

if [[ -n "${EMBEDDING_API_KEY:-}" ]]; then
    EMBED_RESP=$(curl -sf "$EMBEDDING_API_URL/embeddings" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $EMBEDDING_API_KEY" \
        -d "{\"model\": \"$EMBEDDING_MODEL\", \"input\": \"test\"}" 2>&1 || true)

    if echo "$EMBED_RESP" | grep -q '"embedding"'; then
        ok "Embedding API OK ($EMBEDDING_MODEL via OpenRouter)"
    else
        warn "Embedding test got unexpected response — check API key and model"
    fi
else
    warn "Skipping embedding test — EMBEDDING_API_KEY not set"
fi

# ── 6. Bridge check ─────────────────────────────────────────────
step "Checking Matrix bridge"

if curl -sf http://localhost:8008/_matrix/client/v3/login &>/dev/null; then
    ok "Synapse is running on :8008"
else
    warn "Synapse not running. Run: bash scripts/setup-bridge.sh"
fi

# ── 7. Initial ingestion ────────────────────────────────────────
step "Initial data check"

EVENT_COUNT=$(docker compose exec -T postgres psql -U openkhang -d openkhang -tAc \
    "SELECT count(*) FROM events;" 2>/dev/null || echo "0")

if [[ "$EVENT_COUNT" -gt 0 ]]; then
    ok "$EVENT_COUNT events already in memory"
else
    if [[ -f .claude/gchat-inbox.jsonl ]]; then
        LINES=$(wc -l < .claude/gchat-inbox.jsonl | tr -d ' ')
        info "$LINES chat messages found. Run ingestion with:"
        info "  services/.venv/bin/python3 services/memory/ingest-chat-history.py"
    else
        info "No chat history yet. Start the listener: bash scripts/matrix-listener.py --daemon"
    fi
fi

# ── 8. Summary ───────────────────────────────────────────────────
step "Setup complete"

cat <<EOF

  ${BOLD}openkhang Digital Twin${NC}
  ━━━━━━━━━━━━━━━━━━━━━

  ${CYAN}Infrastructure:${NC}
    Postgres + pgvector  → localhost:5433
    Redis                → localhost:6379
    Embeddings (bge-m3)  → OpenRouter API

  ${CYAN}Commands:${NC}
    Start dashboard:     bash scripts/run-dashboard.sh
    Start chat listener: python3 scripts/matrix-listener.py --daemon
    Ingest chat history: services/.venv/bin/python3 services/memory/ingest-chat-history.py
    Run tests:           services/.venv/bin/python3 -m pytest services/agent/tests/ -v

  ${CYAN}Dashboard:${NC}
    http://localhost:8000

  ${CYAN}Configuration:${NC}
    Persona:    config/persona.yaml
    Thresholds: config/confidence_thresholds.yaml
    Workflows:  config/workflows/

  ${CYAN}Documentation:${NC}
    README.md for full guide

EOF
