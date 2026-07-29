#!/usr/bin/env bash
# 프론트엔드(Vite 개발 서버)를 백그라운드로 기동한다.
#
# 사용법: scripts/start-frontend.sh
# 환경변수로 조정 가능:
#   FRONTEND_HOST 기본 127.0.0.1 (외부 노출하려면 0.0.0.0 — DEPLOYMENT.md의
#                 SSH 포트포워딩 권장 사항 참고)
#   FRONTEND_PORT 기본 5173
#
# VITE_API_BASE_URL 등은 frontend/.env에서 읽는다(docs/DEPLOYMENT.md 표준
# 절차와 동일) — 이 스크립트가 임의로 override하지 않는다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

FRONTEND_DIR="$REPO_ROOT/frontend"
PID_FILE="$RUN_DIR/frontend.pid"
LOG_FILE="$FRONTEND_DIR/frontend.log"
HOST="${FRONTEND_HOST:-127.0.0.1}"
PORT="${FRONTEND_PORT:-5173}"

if is_running "$PID_FILE"; then
  echo "frontend: 이미 실행 중 (pid $(cat "$PID_FILE"), log: $LOG_FILE)"
  exit 0
fi

cd "$FRONTEND_DIR"

if [ ! -d node_modules ]; then
  echo "frontend: node_modules가 없다 — 먼저 'npm install'을 실행해라" >&2
  exit 1
fi

# `npm run dev`(npm 래퍼) 대신 vite 바이너리를 직접 실행한다 — npm이 감싸면
# 기록되는 PID가 npm 프로세스라서, 종료 시 실제 vite 서버가 안 죽고 남을 수 있다.
setsid nohup node_modules/.bin/vite --host "$HOST" --port "$PORT" --strictPort \
  > "$LOG_FILE" 2>&1 < /dev/null &
disown
echo $! > "$PID_FILE"

echo "frontend: 시작됨 (pid $(cat "$PID_FILE"), http://${HOST}:${PORT}, log: $LOG_FILE)"
