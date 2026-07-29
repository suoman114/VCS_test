"""SSHConnector.run_command 단위 테스트 — pty 요청 여부 검증.

실제 네트워크 연결은 하지 않는다 — `asyncssh.connect`를 monkeypatch해서 가짜
연결을 반환하고, `conn.run()`에 전달되는 `term_type`/`term_size` 인자를 기록한다.

배경: 실제 VCS 계정의 로그인 셸이 csh/tcsh이고 `.cshrc`가 무조건 `stty`를
호출해서, pty 없는(비대화형) SSH exec에서 `stty: standard input:
Inappropriate ioctl for device`로 실패해 원래 명령 결과를 가려버리는 문제가
있었다(2026-07-29 실 서버에서 확인). `run_command`가 기본적으로 pty를
요청하도록 고쳐서 해결했다 (`app/services/ssh_connector/client.py`).

`term_type="dumb"`도 시도해봤지만 효과가 없었고, 그 다음 시도한 `term_size`
0x0 이론도 아니었다(둘 다 실 서버 진단 스크립트로 반증됨). 최종적으로
verbose 로그로 확인한 진짜 원인은 인코딩이었다: pcap 샘플 파일명 중 일부가
EUC-KR 등 비-UTF-8 인코딩이라, asyncssh 기본 UTF-8 strict 디코딩이 실패하면
그 세션만이 아니라 SSH 커넥션 전체가 `MSG_DISCONNECT`로 끊어지면서 이미 받은
출력이 전부 버려졌다(exit_status=0은 디코딩 실패 전에 받은 값이라 남아있고
stdout/stderr만 텅 빔). `errors="replace"`로 해결했다(`term_type`/`term_size`
수정은 근본 원인이 아니었지만 pty 자체는 여전히 필요해 유지한다).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

import app.services.ssh_connector.client as ssh_client_module
from app.services.ssh_connector.client import SSHConnector, SSHTarget


@dataclass
class _FakeRunResult:
    exit_status: int = 0
    stdout: str = "ok"
    stderr: str = ""


class _FakeProcess:
    def __init__(self, *, wait_closed_hangs: bool = False) -> None:
        self.stdout = _EmptyAsyncIterable()
        self.terminated = False
        self._wait_closed_hangs = wait_closed_hangs

    def terminate(self) -> None:
        self.terminated = True

    async def wait_closed(self) -> None:
        if self._wait_closed_hangs:
            await asyncio.sleep(3600)


class _EmptyAsyncIterable:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _FakeConnection:
    def __init__(self, *, process_wait_closed_hangs: bool = False, conn_wait_closed_hangs: bool = False) -> None:
        self.run_calls: list[dict[str, object]] = []
        self.create_process_calls: list[dict[str, object]] = []
        self._process_wait_closed_hangs = process_wait_closed_hangs
        self._conn_wait_closed_hangs = conn_wait_closed_hangs

    async def run(
        self,
        command,
        *,
        check=False,
        timeout=None,
        term_type=None,
        term_size=None,
        errors=None,
    ):
        self.run_calls.append(
            {
                "command": command,
                "check": check,
                "timeout": timeout,
                "term_type": term_type,
                "term_size": term_size,
                "errors": errors,
            }
        )
        return _FakeRunResult()

    async def create_process(
        self,
        command,
        *,
        errors=None,
        term_type=None,
        term_size=None,
    ):
        self.create_process_calls.append(
            {
                "command": command,
                "errors": errors,
                "term_type": term_type,
                "term_size": term_size,
            }
        )
        return _FakeProcess(wait_closed_hangs=self._process_wait_closed_hangs)

    def is_closed(self) -> bool:
        return False

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        if self._conn_wait_closed_hangs:
            await asyncio.sleep(3600)


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
    assert fake_conn.run_calls[0]["term_type"] == "xterm"
    assert fake_conn.run_calls[0]["term_size"] == (80, 24)
    assert fake_conn.run_calls[0]["errors"] == "replace"


@pytest.mark.asyncio
async def test_run_command_request_pty_false_skips_pty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_conn = _FakeConnection()

    async def _fake_connect(**kwargs: object) -> _FakeConnection:
        return fake_conn

    monkeypatch.setattr(ssh_client_module.asyncssh, "connect", _fake_connect)

    connector = SSHConnector(SSHTarget(host="fake-host"))
    await connector.run_command("ls", request_pty=False)

    assert fake_conn.run_calls[0]["term_type"] is None
    assert fake_conn.run_calls[0]["term_size"] is None


@pytest.mark.asyncio
async def test_tail_file_requests_pty_and_replace_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """`tail_file`도 `run_command`와 동일하게 pty를 요청해야 한다.

    이 함수는 그동안 pty 없이 `create_process`를 호출하고 있었는데,
    `run_command`를 깨뜨렸던 것과 같은 부류의 셸 시작 스크립트 문제가 여기도
    남아있어 실 서버에서 tail 세션이 예기치 않게 끊긴다는 리포트가 있었다.
    """
    fake_conn = _FakeConnection()

    async def _fake_connect(**kwargs: object) -> _FakeConnection:
        return fake_conn

    monkeypatch.setattr(ssh_client_module.asyncssh, "connect", _fake_connect)

    connector = SSHConnector(SSHTarget(host="fake-host"))
    lines = [line async for line in connector.tail_file("/home/vcs/vcsm/logs/vcsm.log")]

    assert lines == []
    assert len(fake_conn.create_process_calls) == 1
    call = fake_conn.create_process_calls[0]
    assert call["command"] == "tail -F /home/vcs/vcsm/logs/vcsm.log"
    assert call["term_type"] == "xterm"
    assert call["term_size"] == (80, 24)
    assert call["errors"] == "replace"


@pytest.mark.asyncio
async def test_connect_times_out_instead_of_hanging_forever(monkeypatch: pytest.MonkeyPatch) -> None:
    """실 서버 장애 재현: TCP handshake가 응답 없이 멈추면 `asyncssh.connect()`가
    영원히 안 끝날 수 있다(asyncssh의 login_timeout은 TCP 연결이 이미 수립된
    뒤에야 시작되므로 이 구간은 보호 대상이 아니다). `connect_timeout`으로
    강제 타임아웃을 걸어 유한 시간 안에 실패하는지 확인한다 — 이게 없으면
    `SshTailSource`의 재연결 시도, 나아가 `CollectorSession.stop()`이
    영원히 멈춰 TestRun이 "running"에서 끝나지 않는 실 서버 장애로
    이어졌다(2026-07-29 확인).
    """

    async def _hangs_forever(**kwargs: object) -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(ssh_client_module.asyncssh, "connect", _hangs_forever)

    connector = SSHConnector(SSHTarget(host="fake-host"), connect_timeout=0.05)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(connector.connect(), timeout=2)


@pytest.mark.asyncio
async def test_tail_file_finally_does_not_hang_when_process_wait_closed_never_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실 서버 장애 재현: tail 채널에 TERM 신호는 보내지지만(로그에 남지만)
    원격이 채널 종료를 확인해주지 않으면 `process.wait_closed()`가 영원히
    안 끝날 수 있었다 — `Sending TERM signal`까지만 찍히고 `Received channel
    close`/`Channel closed`는 전혀 없이 멈추는 실 서버 로그로 확인됐다
    (2026-07-29). `close_timeout`으로 이 대기도 유한 시간에 포기해야 한다.
    """
    fake_conn = _FakeConnection(process_wait_closed_hangs=True)

    async def _fake_connect(**kwargs: object) -> _FakeConnection:
        return fake_conn

    monkeypatch.setattr(ssh_client_module.asyncssh, "connect", _fake_connect)

    connector = SSHConnector(SSHTarget(host="fake-host"), close_timeout=0.05)

    async def _drain() -> None:
        async for _ in connector.tail_file("/home/vcs/vcsm/logs/vcsm.log"):
            pass

    await asyncio.wait_for(_drain(), timeout=2)  # 안 걸리면(=finally가 안 끝나면) 여기서 실패


@pytest.mark.asyncio
async def test_close_does_not_hang_when_conn_wait_closed_never_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SSHConnector.close()`도 동일한 문제가 있었다 — `conn.wait_closed()`가
    영원히 안 끝나면 세션 정리 전체가 멈춘다."""
    fake_conn = _FakeConnection(conn_wait_closed_hangs=True)

    async def _fake_connect(**kwargs: object) -> _FakeConnection:
        return fake_conn

    monkeypatch.setattr(ssh_client_module.asyncssh, "connect", _fake_connect)

    connector = SSHConnector(SSHTarget(host="fake-host"), close_timeout=0.05)
    await connector.connect()

    await asyncio.wait_for(connector.close(), timeout=2)
