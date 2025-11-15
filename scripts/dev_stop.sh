#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"
# 環境変数を取り込む（PORT_BACKEND/PORT_FRONTEND など）
if [ -f .env ]; then
  set -a; source .env; set +a
fi

# 1) PIDファイルに記録されたプロセスを停止
for f in backend_uvicorn.pid frontend_vite.pid; do
  if [ -f "$f" ]; then
    PID=$(cat "$f" 2>/dev/null || true)
    if [ -n "$PID" ]; then
      kill "$PID" 2>/dev/null || true
      # 親が --reload で子を残すケースに備えて少し待機
      sleep 0.3
      # 親プロセス配下の子も巻き取る
      if command -v pgrep >/dev/null 2>&1; then
        CPIDS=$(pgrep -P "$PID" 2>/dev/null || true)
        [ -n "$CPIDS" ] && kill $CPIDS 2>/dev/null || true
      fi
    fi
    rm -f "$f"
  fi
done

# 2) パターンマッチでuvicorn(parent/child)を停止（本リポのアプリに限定）
if command -v pkill >/dev/null 2>&1; then
  pkill -f "uvicorn backend.main:app" 2>/dev/null || true
fi

# 3) 既定ポートのリスナーを強制停止（安全に実行可能）
# 値は .env の PORT_BACKEND/PORT_FRONTEND を尊重、未定義時は 8000/5173
for p in "${PORT_BACKEND:-8000}" "${PORT_FRONTEND:-5173}"; do
  if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -t -iTCP:"$p" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
      echo "[dev] Killing PIDs on port $p: $PIDS"
      kill $PIDS 2>/dev/null || true
      sleep 0.2
      # まだ残っている場合は強制終了
      PIDS2=$(lsof -t -iTCP:"$p" -sTCP:LISTEN 2>/dev/null || true)
      if [ -n "$PIDS2" ]; then
        echo "[dev] Forcing kill on port $p: $PIDS2"
        kill -9 $PIDS2 2>/dev/null || true
      fi
    fi
  fi
done

echo "[dev] stopped."
