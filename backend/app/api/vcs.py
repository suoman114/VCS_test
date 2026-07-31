"""VCS 서버 자체를 조회하는 보조 API (Test Case 등록 폼 지원용).

실 SSH 접속이 필요한 엔드포인트라, 연결 실패 시 502로 응답한다(클라이언트가
"서버 문제"와 "VCS 연결 문제"를 구분할 수 있게).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.services.mcptt.scenario_files import list_mcptt_scenario_files
from app.services.volte.sample_files import list_volte_sample_files

router = APIRouter(prefix="/vcs", tags=["vcs"])


@router.get("/volte-sample-files")
async def get_volte_sample_files() -> dict[str, list[str]]:
    """VoLTE Test Case 등록 폼의 pcap 샘플 select box용 목록.

    `Settings.vctp_sample_dir`(기본 `/home/vcs/vctp/sample`)의 파일 목록을
    VCS에 SSH로 접속해 조회한다.
    """
    try:
        files = await list_volte_sample_files()
    except Exception as exc:  # noqa: BLE001 - SSH 연결 실패 등 다양한 예외를 502로 수렴
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"items": files}


@router.get("/mcptt-scenario-files")
async def get_mcptt_scenario_files() -> dict[str, list[str]]:
    """McPTT Test Case 등록 폼의 시나리오 XML select box용 목록.

    `Settings.mcptt_sim_dir`(기본 `/root/mcptt_sim`)의 `*.xml` 파일 목록을
    SIPp 전용 호스트에 SSH로 접속해 조회한다.
    """
    try:
        files = await list_mcptt_scenario_files()
    except Exception as exc:  # noqa: BLE001 - SSH 연결 실패 등 다양한 예외를 502로 수렴
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"items": files}
