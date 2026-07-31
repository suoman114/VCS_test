"""GET /api/health 통합 테스트 — VCS SSH/SIPp 실제 연결 확인 로직 검증.

실제 네트워크 연결은 하지 않는다: 실제 연결 확인은 `app.services.ssh_health`
(설정 화면의 "연결 테스트" 버튼과 공유하는 모듈)로 옮겨졌으므로, 그 모듈의
`SSHConnector`/`DEFAULT_CONNECT_TIMEOUT_SEC`를 가짜 커넥터로 monkeypatch해서
성공/실패/타임아웃을 흉내낸다. `app.api.health.get_settings`를 바꿔치기해서
호스트 설정 여부(unknown 케이스)와 `sipp_exec_mode` local/ssh 분기를
검증한다.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

import app.api.health as health_module
import app.services.ssh_health as ssh_health_module
from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


class _FakeOkConnector:
    def __init__(self, target: object) -> None:
        self.target = target

    async def run_command(self, command: str) -> "_Result":
        return _Result(exit_status=0)

    async def close(self) -> None:
        return None


class _FakeFailingConnector:
    def __init__(self, target: object) -> None:
        self.target = target

    async def run_command(self, command: str) -> "_Result":
        return _Result(exit_status=1)

    async def close(self) -> None:
        return None


class _FakeHangingConnector:
    def __init__(self, target: object) -> None:
        self.target = target

    async def run_command(self, command: str) -> "_Result":
        await asyncio.sleep(10)
        return _Result(exit_status=0)

    async def close(self) -> None:
        return None


class _Result:
    def __init__(self, exit_status: int) -> None:
        self.exit_status = exit_status

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


@pytest.mark.asyncio
async def test_health_reports_unknown_when_vcs_host_not_configured(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_module, "get_settings", lambda: _settings(sipp_exec_mode="local"))
    monkeypatch.setattr(health_module.shutil, "which", lambda _name: "/usr/bin/sipp")

    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["vcs_ssh"] == "unknown"
    assert body["sipp"] == "ok"


@pytest.mark.asyncio
async def test_health_reports_ok_when_ssh_connects(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: _settings(vcs_ssh_host="192.168.7.64", sipp_exec_mode="local"),
    )
    monkeypatch.setattr(ssh_health_module, "SSHConnector", _FakeOkConnector)
    monkeypatch.setattr(health_module.shutil, "which", lambda _name: None)

    response = await client.get("/api/health")

    body = response.json()
    assert body["vcs_ssh"] == "ok"
    assert body["sipp"] == "error"


@pytest.mark.asyncio
async def test_health_reports_error_when_ssh_command_fails(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: _settings(vcs_ssh_host="192.168.7.64"),
    )
    monkeypatch.setattr(ssh_health_module, "SSHConnector", _FakeFailingConnector)

    response = await client.get("/api/health")

    assert response.json()["vcs_ssh"] == "error"


@pytest.mark.asyncio
async def test_health_reports_error_on_timeout(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: _settings(vcs_ssh_host="192.168.7.64"),
    )
    monkeypatch.setattr(ssh_health_module, "SSHConnector", _FakeHangingConnector)
    monkeypatch.setattr(ssh_health_module, "DEFAULT_CONNECT_TIMEOUT_SEC", 0.05)

    response = await client.get("/api/health")

    assert response.json()["vcs_ssh"] == "error"


@pytest.mark.asyncio
async def test_health_checks_sipp_over_ssh_when_exec_mode_is_ssh(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: _settings(
            vcs_ssh_host="192.168.7.64",
            sipp_exec_mode="ssh",
            sipp_ssh_host="192.168.7.70",
        ),
    )
    monkeypatch.setattr(ssh_health_module, "SSHConnector", _FakeOkConnector)

    response = await client.get("/api/health")

    body = response.json()
    assert body["vcs_ssh"] == "ok"
    assert body["sipp"] == "ok"
