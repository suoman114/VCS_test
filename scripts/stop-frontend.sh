#!/usr/bin/env bash
# scripts/start-frontend.sh로 띄운 프론트엔드를 종료한다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

stop_pid_file "$RUN_DIR/frontend.pid" "frontend"
