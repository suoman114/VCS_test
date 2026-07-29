#!/usr/bin/env bash
# 백엔드(FastAPI/uvicorn)를 백그라운드로 기동한다.
#
# 사용법: scripts/start-backend.sh
# 환경변수로 조정 가능:
#   BACKEND_HOST   기본 127.0.0.1 (외부 노출하려면 0.0.0.0 — DEPLOYMENT.md의
#                  SSH 포트포워딩 권장 사항 참고)
#   BACKEND_PORT   기본 8000
#   BACKEND_RELOAD 1로 주면 --reload 추가(코드 변경 시 자동 재기동, 개발용)
#
# .venv가 backend/에 있으면 자동으로 activate한다(docs/DEPLOYMENT.md 표준 절차).
# 없으면 시스템 python3를 그대로 쓴다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

BACKEND_DIR="$REPO_ROOT/backend"
PID_FILE="$RUN_DIR/backend.pid"
LOG_FILE="$BACKEND_DIR/backend.log"
HOST="${BACKEND_HOST:-127.0.0.1}"
PORT="${BACKEND_PORT:-8000}"

if is_running "$PID_FILE"; then
  echo "backend: 이미 실행 중 (pid $(cat "$PID_FILE"), log: $LOG_FILE)"
  exit 0
fi

cd "$BACKEND_DIR"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

RELOAD_ARGS=()
if [ "${BACKEND_RELOAD:-0}" = "1" ]; then
  RELOAD_ARGS=(--reload)
fi

setsid nohup python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT" "${RELOAD_ARGS[@]}" \
  > "$LOG_FILE" 2>&1 < /dev/null &
disown
echo $! > "$PID_FILE"

echo "backend: 시작됨 (pid $(cat "$PID_FILE"), http://${HOST}:${PORT}, log: $LOG_FILE)"
