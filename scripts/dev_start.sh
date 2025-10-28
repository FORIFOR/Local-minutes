#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"
if [ -f .env ]; then
  set -a; source .env; set +a
fi
echo "[dev] backend起動..."
# PORT が未定義でも安全に起動できるように直接既定値を使用
(. .venv/bin/activate && uvicorn backend.main:app --reload --host 127.0.0.1 --port "${PORT_BACKEND:-8000}" & echo $! > backend_uvicorn.pid)
sleep 1
echo "[dev] frontend起動..."
(cd frontend && npm run dev -- --host 127.0.0.1 --port ${PORT_FRONTEND:-5173} ${FRONTEND_OPEN_FLAG:---open} & echo $! > ../frontend_vite.pid)
echo "[dev] started."
