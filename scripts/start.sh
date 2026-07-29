#!/usr/bin/env bash
# 백엔드 + 프론트엔드를 한 번에 기동한다. 개별 기동은 start-backend.sh /
# start-frontend.sh를 따로 쓰면 된다.
set -euo pipefail
DIR="$(dirname "${BASH_SOURCE[0]}")"

"$DIR/start-backend.sh"
"$DIR/start-frontend.sh"
