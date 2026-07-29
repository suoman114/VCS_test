#!/usr/bin/env bash
# scripts/start-backend.sh로 띄운 백엔드를 종료한다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

stop_pid_file "$RUN_DIR/backend.pid" "backend"
