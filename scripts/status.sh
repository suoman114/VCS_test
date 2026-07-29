#!/usr/bin/env bash
# 백엔드/프론트엔드가 떠 있는지, 백엔드 헬스체크가 통과하는지 확인한다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

if is_running "$BACKEND_PID_FILE"; then
  echo "backend:  실행 중 (pid $(cat "$BACKEND_PID_FILE"))"
  if command -v curl >/dev/null 2>&1; then
    if curl -s -o /dev/null -w '' --max-time 2 "http://${BACKEND_HOST}:${BACKEND_PORT}/api/health"; then
      echo "  health: OK (http://${BACKEND_HOST}:${BACKEND_PORT}/api/health)"
    else
      echo "  health: 응답 없음 (기동 중이거나 포트/호스트 설정 확인 필요)"
    fi
  fi
else
  echo "backend:  실행 중이 아님"
fi

if is_running "$FRONTEND_PID_FILE"; then
  echo "frontend: 실행 중 (pid $(cat "$FRONTEND_PID_FILE"), http://${FRONTEND_HOST}:${FRONTEND_PORT})"
else
  echo "frontend: 실행 중이 아님"
fi
