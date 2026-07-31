"""VCS/SIPp 접속 설정 조회/수정 API (CLAUDE.md §13: 호스트/계정을 .env에만
채우던 것을 대시보드에서도 편집 가능하게 함).

`.env`(`Settings`)는 여전히 기본값을 제공하고, 이 API가 다루는
`VcsSettings`(DB, 싱글턴 1행)는 그 위에 얹는 오버라이드다. 병합/우선순위
로직은 `app.services.vcs_settings_store`에 있고, 이 라우터는 그 결과를
API 스키마로 변환만 한다.
"""
from __future__ import annotations

import asyncio
import shutil

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.vcs_settings import ConnectionTestResult, VcsSettingsRead, VcsSettingsUpdate
from app.services.ssh_connector import SSHConnector
from app.services.ssh_health import check_ssh_reachable
from app.services.vcs_settings_store import (
    apply_update,
    effective_value,
    get_or_create,
    resolve_sipp_root_password,
    resolve_sipp_target,
    resolve_vcs_target,
)

router = APIRouter(prefix="/settings", tags=["settings"])


def _to_read(row, settings) -> VcsSettingsRead:
    return VcsSettingsRead(
        vcs_ssh_host=effective_value(row, "vcs_ssh_host", settings),
        vcs_ssh_port=effective_value(row, "vcs_ssh_port", settings) or 22,
        vcs_ssh_username=effective_value(row, "vcs_ssh_username", settings),
        vcs_ssh_password_set=bool(effective_value(row, "vcs_ssh_password", settings)),
        vcs_ssh_private_key_path=effective_value(row, "vcs_ssh_private_key_path", settings),
        vcs_ssh_known_hosts=effective_value(row, "vcs_ssh_known_hosts", settings),
        sipp_exec_mode=effective_value(row, "sipp_exec_mode", settings) or "local",
        sipp_ssh_host=effective_value(row, "sipp_ssh_host", settings),
        sipp_ssh_port=effective_value(row, "sipp_ssh_port", settings) or 22,
        sipp_ssh_username=effective_value(row, "sipp_ssh_username", settings),
        sipp_ssh_password_set=bool(effective_value(row, "sipp_ssh_password", settings)),
        sipp_ssh_private_key_path=effective_value(row, "sipp_ssh_private_key_path", settings),
        sipp_ssh_root_password_set=bool(effective_value(row, "sipp_ssh_root_password", settings)),
        vcs_mariadb_user=effective_value(row, "vcs_mariadb_user", settings),
        vcs_mariadb_password_set=bool(effective_value(row, "vcs_mariadb_password", settings)),
        vcs_mariadb_database=effective_value(row, "vcs_mariadb_database", settings),
        updated_at=row.updated_at,
    )


@router.get("/vcs", response_model=VcsSettingsRead)
def get_vcs_settings(db: Session = Depends(get_db)) -> VcsSettingsRead:
    row = get_or_create(db)
    return _to_read(row, get_settings())


@router.patch("/vcs", response_model=VcsSettingsRead)
def update_vcs_settings(body: VcsSettingsUpdate, db: Session = Depends(get_db)) -> VcsSettingsRead:
    row = get_or_create(db)
    apply_update(row, body.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(row)
    return _to_read(row, get_settings())


@router.post("/vcs/test-connection", response_model=ConnectionTestResult)
async def test_vcs_connection() -> ConnectionTestResult:
    try:
        target = resolve_vcs_target()
    except ValueError as exc:
        return ConnectionTestResult(ok=False, message=str(exc))
    ok, message = await check_ssh_reachable(target)
    return ConnectionTestResult(ok=ok, message=message)


@router.post("/sipp/test-connection", response_model=ConnectionTestResult)
async def test_sipp_connection(db: Session = Depends(get_db)) -> ConnectionTestResult:
    row = get_or_create(db)
    settings = get_settings()
    exec_mode = effective_value(row, "sipp_exec_mode", settings) or "local"
    if exec_mode != "ssh":
        if shutil.which("sipp"):
            return ConnectionTestResult(ok=True, message="로컬 sipp 실행 파일 확인됨")
        return ConnectionTestResult(ok=False, message="로컬에서 sipp 실행 파일을 찾을 수 없음 (PATH 확인)")

    try:
        target = resolve_sipp_target()
    except ValueError as exc:
        return ConnectionTestResult(ok=False, message=str(exc))

    root_password = resolve_sipp_root_password(settings)
    if not root_password:
        ok, message = await check_ssh_reachable(target)
        return ConnectionTestResult(ok=ok, message=message)

    # root 비밀번호가 설정돼 있으면 SSH 접속뿐 아니라 su - root 전환까지
    # 실제로 확인한다 — 이 체인(sysadm 접속 -> su root)이 실제 배포 환경의
    # 핵심 요구사항이라, 단순 접속 성공만으로는 충분한 검증이 아니다.
    connector = SSHConnector(target)
    try:
        result = await asyncio.wait_for(connector.run_command_as_su("whoami", root_password), timeout=10)
        if result.ok and "root" in result.stdout:
            return ConnectionTestResult(
                ok=True, message=f"{target.host}:{target.port} 접속 성공, su - root 전환 확인됨"
            )
        return ConnectionTestResult(
            ok=False, message=f"su - root 전환 실패: {(result.stdout or result.stderr).strip()[:200]}"
        )
    except Exception as exc:  # noqa: BLE001 - 인증 실패/타임아웃 등 사유가 다양해 메시지 그대로 전달
        return ConnectionTestResult(ok=False, message=f"{target.host}:{target.port} — {exc}")
    finally:
        await connector.close()
