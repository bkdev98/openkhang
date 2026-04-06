#!/bin/bash
# Run the openkhang dashboard on port 8000
# Usage: ./scripts/run-dashboard.sh [--port 8080]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load .env if present
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

PORT="${1:-8000}"
RELOAD="${RELOAD:-true}"

echo "Starting openkhang dashboard on http://0.0.0.0:${PORT}"

cd "$PROJECT_ROOT"
exec services/.venv/bin/uvicorn \
    services.dashboard.app:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    $( [[ "$RELOAD" == "true" ]] && echo "--reload" )
