"""헬스체크 라우터.

`/api/health`는 API 서버 자체의 생존 여부(`status`)뿐 아니라 VCS/SIPp에
실제로 SSH 연결 가능한지도 확인해서 대시보드 배지(HealthBadge)에 반영한다
(`frontend/src/api/types.ts`의 `HealthResponse.vcs_ssh`/`sipp`가 이미
이 값을 소비하도록 되어 있었다 — 지금까지는 백엔드가 항상 값을 안 줘서
"확인중"으로만 보였다).

매 호출마다 실제 연결을 시도하므로(짧은 타임아웃), 대시보드가 10초 간격으로
폴링해도 과도한 지연이 되지 않게 타임아웃을 짧게 잡는다.
"""
from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter

from app.core.config import Settings, get_settings
from app.services.ssh_connector import SSHConnector, SSHTarget

router = APIRouter(tags=["health"])

HealthState = Literal["ok", "error", "unknown"]

_CONNECT_TIMEOUT_SEC = 3.0


async def _check_ssh(build_target: Callable[[], SSHTarget]) -> HealthState:
    """SSH 연결 + 아주 가벼운 명령(`true`) 실행으로 "정말 붙는지"를 확인한다.

    `build_target`이 `ValueError`를 내면(호스트가 `.env`에 아직 설정 안 됨)
    "unknown"(회색, 확인중)으로, 연결/실행이 실패하거나 타임아웃되면
    "error"로 본다. `asyncio.wait_for`로 연결 시도 자체(TCP 핸드셰이크
    포함)까지 통째로 타임아웃을 씌운다 — 호스트가 방화벽에 막혀 응답이
    아예 없는 경우 OS 기본 TCP 타임아웃(수십 초)까지 기다리지 않게 하기 위함.
    """
    try:
        target = build_target()
    except ValueError:
        return "unknown"

    connector = SSHConnector(target)
    try:
        result = await asyncio.wait_for(connector.run_command("true"), timeout=_CONNECT_TIMEOUT_SEC)
        return "ok" if result.ok else "error"
    except Exception:  # noqa: BLE001 - 타임아웃/인증실패/네트워크 등 사유 다양, 배지엔 ok/error만 필요
        return "error"
    finally:
        await connector.close()


async def _check_sipp(settings: Settings) -> HealthState:
    """SIPp "실행 가능" 여부. 실행 위치(local/ssh)에 따라 확인 방법이 다르다."""
    if settings.sipp_exec_mode == "ssh":
        return await _check_ssh(lambda: SSHTarget.from_sipp_settings(settings))
    return "ok" if shutil.which("sipp") else "error"


@router.get("/health")
async def health_check() -> dict[str, str]:
    settings = get_settings()

    vcs_ssh_state, sipp_state = await asyncio.gather(
        _check_ssh(lambda: SSHTarget.from_vcs_settings(settings)),
        _check_sipp(settings),
    )

    return {"status": "ok", "vcs_ssh": vcs_ssh_state, "sipp": sipp_state}
