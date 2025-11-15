#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

# .env / .env.local を読み込み（local が優先）
if [ -f .env ]; then
  set -a; source .env; set +a
fi
if [ -f .env.local ]; then
  set -a; source .env.local; set +a
fi

HOST="${DEV_BACKEND_HOST:-0.0.0.0}"
WANTED_PORT="${PORT_BACKEND:-8000}"

# 空きポート探索（PORT_BACKEND優先、だめなら +0..+10 の範囲）
pick_port() {
  local start="$1"
  for off in $(seq 0 10); do
    local p=$((start+off))
    # まずLISTENの有無を確認
    if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
      continue
    fi
    # OSレベルで実際にbind可能か確認
    HOST_ENV="$HOST" python3 - "$p" <<'PY' >/dev/null 2>&1
import socket, sys, os
p=int(sys.argv[1])
host=os.getenv("HOST_ENV","127.0.0.1")
s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind((host, p))
    s.close()
    sys.exit(0)
except OSError:
    sys.exit(1)
PY
    if [ $? -eq 0 ]; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

PORT=$(pick_port "$WANTED_PORT") || {
  echo "[dev-backend] no free port around $WANTED_PORT"
  exit 1
}

# 選んだポートを書き出して他プロセスと共有
echo -n "$PORT" > "$ROOT_DIR/.backend_port"

echo "[dev-backend] uvicorn starting on http://$HOST:$PORT"
export PORT_BACKEND="$PORT"
. .venv/bin/activate
exec uvicorn backend.main:app --reload --host "$HOST" --port "$PORT"
