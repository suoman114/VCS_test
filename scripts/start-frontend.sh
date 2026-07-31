#!/usr/bin/env bash
# 프론트엔드(Vite 개발 서버)를 백그라운드로 기동한다.
#
# 사용법: scripts/start-frontend.sh
# 환경변수로 조정 가능:
#   FRONTEND_HOST 기본 0.0.0.0(모든 인터페이스에 노출 — 브라우저에서 서버
#                 IP로 직접 접속하는 배포 환경 기준). SSH 포트포워딩만 쓰고
#                 싶으면 FRONTEND_HOST=127.0.0.1로 좁혀서 실행해라.
#   FRONTEND_PORT 기본 5173
#
# VITE_API_BASE_URL 등은 frontend/.env에서 읽는다(docs/DEPLOYMENT.md 표준
# 절차와 동일) — 이 스크립트가 임의로 override하지 않는다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

FRONTEND_DIR="$REPO_ROOT/frontend"
PID_FILE="$RUN_DIR/frontend.pid"
LOG_FILE="$FRONTEND_DIR/frontend.log"
HOST="${FRONTEND_HOST:-0.0.0.0}"
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
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

# 백그라운드 기동은 부모 스크립트가 자식의 실제 성공/실패를 못 보므로,
# 잠깐 기다렸다가 진짜 살아있는지 확인하고 나서야 성공을 보고한다
# (start-backend.sh와 동일한 이유 — 포트 충돌 등으로 vite가 바로 죽어도
# 이게 없으면 "시작됨"이 잘못 찍힌다).
sleep 1
if kill -0 "$NEW_PID" 2>/dev/null; then
  echo "frontend: 시작됨 (pid $NEW_PID, http://${HOST}:${PORT}, log: $LOG_FILE)"
else
  rm -f "$PID_FILE"
  echo "frontend: 기동 실패 — 로그 확인: $LOG_FILE" >&2
  tail -n 20 "$LOG_FILE" >&2 || true
  exit 1
fi
