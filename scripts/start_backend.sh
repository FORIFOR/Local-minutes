#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ -f .env ]; then
  set -a; source .env; set +a
fi

HOST="0.0.0.0"
PORT="${PORT_BACKEND:-8000}"

echo "[start-backend] uvicorn starting on http://$HOST:$PORT"
. .venv/bin/activate
exec uvicorn backend.main:app --host "$HOST" --port "$PORT"

