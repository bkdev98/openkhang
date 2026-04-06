#!/usr/bin/env bash
# uninstall.sh — Remove all openkhang services, data, and local config
#
# What it removes:
#   1. Docker containers (postgres, redis)
#   2. Docker volumes (pgdata, ollama legacy)
#   3. Docker images (pgvector, redis)
#   4. Python virtual environment (services/.venv)
#   5. Local .env file
#   6. Meridian process (if running)
#   7. Matrix bridge containers (optional)
#
# What it keeps:
#   - Source code (git repo)
#   - .env.example (template)
#   - config/ files (persona, thresholds, workflows)
#   - chat history files (.claude/gchat-inbox.jsonl)
#
# Usage: bash scripts/uninstall.sh [--all]
#   --all: Also remove Matrix bridge stack and chat history

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

REMOVE_ALL=false
[[ "${1:-}" == "--all" ]] && REMOVE_ALL=true

echo ""
echo -e "${BOLD}openkhang Uninstaller${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "This will remove:"
echo "  - Docker containers (postgres, redis)"
echo "  - Docker volumes (all data — memories, events, drafts)"
echo "  - Python virtual environment"
echo "  - .env file (contains your API keys)"
if [[ "$REMOVE_ALL" == true ]]; then
    echo "  - Matrix bridge stack (~/.mautrix-googlechat)"
    echo "  - Chat history files"
fi
echo ""
echo -e "${RED}WARNING: All memory data will be permanently deleted.${NC}"
echo ""
read -rp "Type 'yes' to confirm: " CONFIRM

if [[ "$CONFIRM" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

# ── 1. Stop Meridian ────────────────────────────────────────────
step "Stopping Meridian"
if pkill -f "meridian" 2>/dev/null; then
    ok "Meridian stopped"
else
    info "Meridian not running"
fi

# ── 2. Stop and remove Docker containers ────────────────────────
step "Stopping Docker containers"
if command -v docker &>/dev/null && docker info &>/dev/null; then
    docker compose down 2>/dev/null && ok "Containers stopped and removed" || info "No containers to stop"

    # Remove legacy Ollama container if it exists
    if docker ps -a --format '{{.Names}}' | grep -q openkhang-ollama; then
        docker rm -f openkhang-ollama 2>/dev/null
        ok "Removed legacy Ollama container"
    fi
else
    warn "Docker not available — skipping container cleanup"
fi

# ── 3. Remove Docker volumes ────────────────────────────────────
step "Removing Docker volumes (database data)"
if command -v docker &>/dev/null && docker info &>/dev/null; then
    for vol in openkhang_openkhang-pgdata openkhang_openkhang-ollama; do
        if docker volume ls -q | grep -q "^${vol}$"; then
            docker volume rm "$vol" 2>/dev/null && ok "Removed volume: $vol"
        fi
    done
    info "All openkhang volumes removed"
else
    warn "Docker not available — skipping volume cleanup"
fi

# ── 4. Remove Docker images (optional, saves disk) ─────────────
step "Removing Docker images"
for img in "pgvector/pgvector:pg17" "redis:7-alpine" "ollama/ollama:latest"; do
    if docker images -q "$img" 2>/dev/null | grep -q .; then
        docker rmi "$img" 2>/dev/null && ok "Removed image: $img" || warn "Could not remove $img (may be used by other projects)"
    fi
done

# ── 5. Remove Python venv ──────────────────────────────────────
step "Removing Python virtual environment"
if [[ -d services/.venv ]]; then
    rm -rf services/.venv
    ok "Removed services/.venv"
else
    info "No venv found"
fi

# ── 6. Remove .env ─────────────────────────────────────────────
step "Removing .env"
if [[ -f .env ]]; then
    rm -f .env
    ok "Removed .env"
else
    info "No .env found"
fi

# ── 7. Optional: Matrix bridge + chat history ──────────────────
if [[ "$REMOVE_ALL" == true ]]; then
    step "Removing Matrix bridge stack"
    BRIDGE_DIR="$HOME/.mautrix-googlechat"
    if [[ -d "$BRIDGE_DIR" ]]; then
        if [[ -f "$BRIDGE_DIR/docker-compose.yml" ]]; then
            (cd "$BRIDGE_DIR" && docker compose down -v 2>/dev/null)
            ok "Bridge containers stopped"
        fi
        rm -rf "$BRIDGE_DIR"
        ok "Removed $BRIDGE_DIR"
    else
        info "No bridge stack found"
    fi

    step "Removing chat history"
    if [[ -f .claude/gchat-inbox.jsonl ]]; then
        rm -f .claude/gchat-inbox.jsonl
        ok "Removed chat history"
    else
        info "No chat history found"
    fi
fi

# ── Summary ────────────────────────────────────────────────────
step "Uninstall complete"
cat <<EOF

  Removed:
    ✓ Docker containers and volumes
    ✓ Docker images (pgvector, redis)
    ✓ Python virtual environment
    ✓ .env configuration
EOF

if [[ "$REMOVE_ALL" == true ]]; then
    echo "    ✓ Matrix bridge stack"
    echo "    ✓ Chat history"
fi

cat <<EOF

  Kept:
    - Source code (this git repo)
    - .env.example (template for fresh setup)
    - config/ files (persona, thresholds, workflows)

  To reinstall:
    bash scripts/onboard.sh

EOF
