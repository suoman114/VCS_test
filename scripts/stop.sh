#!/usr/bin/env bash
# 백엔드 + 프론트엔드를 한 번에 종료한다.
set -euo pipefail
DIR="$(dirname "${BASH_SOURCE[0]}")"

"$DIR/stop-frontend.sh"
"$DIR/stop-backend.sh"
