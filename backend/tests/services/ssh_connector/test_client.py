"""SSHConnector.run_command 단위 테스트 — pty 요청 여부 검증.

실제 네트워크 연결은 하지 않는다 — `asyncssh.connect`를 monkeypatch해서 가짜
연결을 반환하고, `conn.run()`에 전달되는 `term_type` 인자를 기록한다.

배경: 실제 VCS 계정의 로그인 셸이 csh/tcsh이고 `.cshrc`가 무조건 `stty`를
호출해서, pty 없는(비대화형) SSH exec에서 `stty: standard input:
Inappropriate ioctl for device`로 실패해 원래 명령 결과를 가려버리는 문제가
있었다(2026-07-29 실 서버에서 확인). `run_command`가 기본적으로 pty를
요청(`term_type="dumb"`)하도록 고쳐서 해결했다 (`app/services/ssh_connector/client.py`).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

import app.services.ssh_connector.client as ssh_client_module
from app.services.ssh_connector.client import SSHConnector, SSHTarget


@dataclass
class _FakeRunResult:
    exit_status: int = 0
    stdout: str = "ok"
    stderr: str = ""


class _FakeConnection:
    def __init__(self) -> None:
        self.run_calls: list[dict[str, object]] = []

    async def run(self, command, *, check=False, timeout=None, term_type=None):
        self.run_calls.append(
            {"command": command, "check": check, "timeout": timeout, "term_type": term_type}
        )
        return _FakeRunResult()

    def is_closed(self) -> bool:
        return False

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_run_command_requests_pty_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_conn = _FakeConnection()

    async def _fake_connect(**kwargs: object) -> _FakeConnection:
        return fake_conn

    monkeypatch.setattr(ssh_client_module.asyncssh, "connect", _fake_connect)

    connector = SSHConnector(SSHTarget(host="fake-host"))
    result = await connector.run_command("ls -1 /home/vcs/vctp/sample")

    assert result.exit_status == 0
    assert len(fake_conn.run_calls) == 1
    assert fake_conn.run_calls[0]["term_type"] == "dumb"


@pytest.mark.asyncio
async def test_run_command_request_pty_false_skips_pty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_conn = _FakeConnection()

    async def _fake_connect(**kwargs: object) -> _FakeConnection:
        return fake_conn

    monkeypatch.setattr(ssh_client_module.asyncssh, "connect", _fake_connect)

    connector = SSHConnector(SSHTarget(host="fake-host"))
    await connector.run_command("ls", request_pty=False)

    assert fake_conn.run_calls[0]["term_type"] is None
