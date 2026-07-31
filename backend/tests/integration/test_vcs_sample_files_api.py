"""GET /api/vcs/volte-sample-files, /api/vcs/mcptt-scenario-files 통합 테스트.

실제 SSH 연결은 하지 않는다: `app.api.vcs.list_volte_sample_files`/
`list_mcptt_scenario_files`(라우터가 import한 이름 그대로)를 monkeypatch해서
성공/실패 케이스를 흉내낸다.
"""
from __future__ import annotations

import httpx
import pytest

import app.api.vcs as vcs_api_module


@pytest.mark.asyncio
async def test_get_volte_sample_files_returns_sorted_list(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 정렬은 app.services.volte.sample_files.list_volte_sample_files의 책임이라
    # (별도로 이미 그 정렬 동작을 검증), 여기서는 라우터가 그 결과를 그대로
    # {"items": [...]}로 감싸는지만 확인한다.
    async def _fake_list(**kwargs: object) -> list[str]:
        return ["imsVideo30sec.pcap", "zzz.pcap"]

    monkeypatch.setattr(vcs_api_module, "list_volte_sample_files", _fake_list)

    response = await client.get("/api/vcs/volte-sample-files")

    assert response.status_code == 200
    assert response.json() == {"items": ["imsVideo30sec.pcap", "zzz.pcap"]}


@pytest.mark.asyncio
async def test_get_volte_sample_files_ssh_failure_returns_502(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_list_raises(**kwargs: object) -> list[str]:
        raise RuntimeError("VCS_SSH_HOST가 설정되지 않았다 (.env 확인)")

    monkeypatch.setattr(vcs_api_module, "list_volte_sample_files", _fake_list_raises)

    response = await client.get("/api/vcs/volte-sample-files")

    assert response.status_code == 502
    assert "VCS_SSH_HOST" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_mcptt_scenario_files_returns_sorted_list(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_list(**kwargs: object) -> list[str]:
        return ["basic_call.xml", "zzz_call.xml"]

    monkeypatch.setattr(vcs_api_module, "list_mcptt_scenario_files", _fake_list)

    response = await client.get("/api/vcs/mcptt-scenario-files")

    assert response.status_code == 200
    assert response.json() == {"items": ["basic_call.xml", "zzz_call.xml"]}


@pytest.mark.asyncio
async def test_get_mcptt_scenario_files_ssh_failure_returns_502(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_list_raises(**kwargs: object) -> list[str]:
        raise RuntimeError("SIPP_SSH_HOST가 설정되지 않았다 (.env 또는 대시보드 설정 확인)")

    monkeypatch.setattr(vcs_api_module, "list_mcptt_scenario_files", _fake_list_raises)

    response = await client.get("/api/vcs/mcptt-scenario-files")

    assert response.status_code == 502
    assert "SIPP_SSH_HOST" in response.json()["detail"]
