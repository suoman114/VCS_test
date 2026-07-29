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
from app.services.ssh_connector import SSHTarget
from app.services.ssh_health import check_ssh_reachable
from app.services.vcs_settings_store import resolve_sipp_exec_mode, resolve_sipp_target, resolve_vcs_target

router = APIRouter(tags=["health"])

HealthState = Literal["ok", "error", "unknown"]


async def _check_ssh(build_target: Callable[[], SSHTarget]) -> HealthState:
    """`build_target`이 `ValueError`를 내면(호스트가 아직 설정 안 됨) "unknown"
    (회색, 확인중)으로, 연결/실행이 실패하거나 타임아웃되면 "error"로 본다.
    실제 연결 확인 자체는 `check_ssh_reachable`(설정 화면의 "연결 테스트"
    버튼과 공유하는 로직)을 그대로 쓴다.
    """
    try:
        target = build_target()
    except ValueError:
        return "unknown"
    ok, _ = await check_ssh_reachable(target)
    return "ok" if ok else "error"


async def _check_sipp(settings: Settings) -> HealthState:
    """SIPp "실행 가능" 여부. 실행 위치(local/ssh, 대시보드 오버라이드 포함)에
    따라 확인 방법이 다르다."""
    if resolve_sipp_exec_mode(settings) == "ssh":
        return await _check_ssh(lambda: resolve_sipp_target(settings))
    return "ok" if shutil.which("sipp") else "error"


@router.get("/health")
async def health_check() -> dict[str, str]:
    settings = get_settings()

    vcs_ssh_state, sipp_state = await asyncio.gather(
        _check_ssh(lambda: resolve_vcs_target(settings)),
        _check_sipp(settings),
    )

    return {"status": "ok", "vcs_ssh": vcs_ssh_state, "sipp": sipp_state}
