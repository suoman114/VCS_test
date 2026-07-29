#!/usr/bin/env bash
# start/stop 스크립트 공용 함수. 각 스크립트가 `source`해서 쓴다.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$REPO_ROOT/storage/run"
mkdir -p "$RUN_DIR"

# PID 파일에 살아있는 프로세스가 있으면 0(성공), 없으면 1을 반환한다.
# 죽은 프로세스의 stale PID 파일은 여기서 지운다.
is_running() {
  local pid_file="$1"
  [ -f "$pid_file" ] || return 1
  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  rm -f "$pid_file"
  return 1
}

# `setsid`로 띄운 프로세스(그룹 리더, PGID == PID)를 정리한다.
# SIGTERM으로 그룹 전체에 보내고, 유예 시간 안에 안 죽으면 SIGKILL한다.
# vite처럼 자식 프로세스(esbuild 등)를 띄우는 경우 PID 하나만 죽이면
# 자식이 남을 수 있어 프로세스 그룹 단위(`kill -- -$pid`)로 정리한다.
stop_pid_file() {
  local pid_file="$1"
  local label="$2"
  local grace_sec="${3:-10}"

  if ! is_running "$pid_file"; then
    echo "${label}: 실행 중이 아님"
    return 0
  fi

  local pid
  pid="$(cat "$pid_file")"
  echo "${label}: 종료 요청 (pid ${pid})"
  kill -TERM -- "-${pid}" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true

  local waited=0
  while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$grace_sec" ]; do
    sleep 1
    waited=$((waited + 1))
  done

  if kill -0 "$pid" 2>/dev/null; then
    echo "${label}: ${grace_sec}초 안에 안 끝나서 SIGKILL"
    kill -KILL -- "-${pid}" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi

  rm -f "$pid_file"
  echo "${label}: 종료됨 (pid ${pid})"
}
