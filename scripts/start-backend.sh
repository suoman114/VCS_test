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

# 배열(RELOAD_ARGS=(--reload) 후 "${RELOAD_ARGS[@]}")을 쓰지 않는다 — bash
# 4.4 미만(CentOS 7 기본 bash 4.2 등, docs/DEPLOYMENT.md 참고)에서는 `set -u`
# 하에서 빈 배열을 확장하면 "unbound variable"로 처리하는 알려진 버그가
# 있다. 여기서 실제로 그 버그에 걸려 uvicorn이 아예 기동되지 않았는데도
# 백그라운드 job이라 부모 스크립트는 실패를 못 보고 "시작됨"을 잘못
# 출력했다 — 아래 생존 확인이 이런 경우를 다시 잡아낸다.
RELOAD_ARG=""
if [ "${BACKEND_RELOAD:-0}" = "1" ]; then
  RELOAD_ARG="--reload"
fi

# shellcheck disable=SC2086  # RELOAD_ARG는 "--reload" 또는 빈 문자열 고정값이라 의도적으로 unquoted
setsid nohup python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT" $RELOAD_ARG \
  > "$LOG_FILE" 2>&1 < /dev/null &
disown
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

# 백그라운드 기동은 부모 스크립트가 자식의 실제 성공/실패를 못 보므로,
# 잠깐 기다렸다가 진짜 살아있는지 확인하고 나서야 성공을 보고한다.
sleep 1
if kill -0 "$NEW_PID" 2>/dev/null; then
  echo "backend: 시작됨 (pid $NEW_PID, http://${HOST}:${PORT}, log: $LOG_FILE)"
else
  rm -f "$PID_FILE"
  echo "backend: 기동 실패 — 로그 확인: $LOG_FILE" >&2
  tail -n 20 "$LOG_FILE" >&2 || true
  exit 1
fi
