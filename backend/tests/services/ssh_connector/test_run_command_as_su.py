"""`SSHConnector.run_command_as_su` 단위 테스트 — su 프롬프트 자동 응답 상태
머신 검증.

root 직접 SSH 로그인이 막힌 배포 환경(sysadm으로 접속 후 `su - root`)
대응으로 추가됐다(2026-07-29). 실제 su 프롬프트를 가진 원격 서버가 없어서
end-to-end로 검증은 못 했다 — 여기서는 PTY 스트림을 흉내내는 가짜
프로세스로 "비밀번호 프롬프트 대기 -> 비밀번호 전송 -> whoami로 su 성공
확인 -> 실제 명령 실행 -> 마커로 출력/exit code 파싱" 상태 머신 자체만
검증한다.
"""
from __future__ import annotations

import asyncio

import pytest

import app.services.ssh_connector.client as ssh_client_module
from app.services.ssh_connector.client import SSHConnector, SSHTarget


class _FakeStdin:
    def __init__(self) -> None:
        self.written: list[str] = []

    def write(self, data: str) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None


class _FakeStdout:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = list(chunks)

    async def read(self, n: int = -1) -> str:
        if not self._chunks:
            return ""  # EOF
        return self._chunks.pop(0)


class _FakeSuProcess:
    def __init__(self, chunks: list[str]) -> None:
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(chunks)
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    async def wait_closed(self) -> None:
        return None


class _FakeConnection:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks
        self.created_processes: list[_FakeSuProcess] = []

    async def create_process(self, **kwargs: object) -> _FakeSuProcess:
        process = _FakeSuProcess(self._chunks)
        self.created_processes.append(process)
        return process

    def is_closed(self) -> bool:
        return False

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


def _patch_connect(monkeypatch: pytest.MonkeyPatch, fake_conn: _FakeConnection) -> None:
    async def _fake_connect(**kwargs: object) -> _FakeConnection:
        return fake_conn

    monkeypatch.setattr(ssh_client_module.asyncssh, "connect", _fake_connect)


@pytest.mark.asyncio
async def test_run_command_as_su_success(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        "Password: ",
        "root\n__SU_CHECK__:0\n",
        "__CMD_START__\nhello world\n__CMD_END__:0\n",
    ]
    fake_conn = _FakeConnection(chunks)
    _patch_connect(monkeypatch, fake_conn)

    connector = SSHConnector(SSHTarget(host="fake-host"))
    result = await connector.run_command_as_su("echo hello world", "root-pw")

    assert result.exit_status == 0
    assert result.stdout == "hello world"

    process = fake_conn.created_processes[0]
    written = "".join(process.stdin.written)
    assert "su - root\n" in written
    assert "root-pw\n" in written  # 비밀번호가 실제로 stdin에 입력됐는지
    assert "echo hello world" in written
    assert process.terminated is True  # 정리(finally)에서 프로세스를 종료했는지


@pytest.mark.asyncio
async def test_run_command_as_su_auth_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """su 인증 실패 시(비밀번호 오류) whoami가 su_user가 아닌 원래 계정을
    돌려주는 상황을 흉내낸다 — exit code만으로는 구분이 안 되므로
    whoami 결과로 판단해야 한다."""
    chunks = [
        "Password: ",
        "sysadm\n__SU_CHECK__:0\n",  # su 실패 -> whoami는 여전히 sysadm
    ]
    fake_conn = _FakeConnection(chunks)
    _patch_connect(monkeypatch, fake_conn)

    connector = SSHConnector(SSHTarget(host="fake-host"))
    with pytest.raises(RuntimeError, match="인증 실패"):
        await connector.run_command_as_su("echo hi", "wrong-pw")


@pytest.mark.asyncio
async def test_run_command_as_su_custom_su_user(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        "Password: ",
        "deploy\n__SU_CHECK__:0\n",
        "__CMD_START__\nok\n__CMD_END__:0\n",
    ]
    fake_conn = _FakeConnection(chunks)
    _patch_connect(monkeypatch, fake_conn)

    connector = SSHConnector(SSHTarget(host="fake-host"))
    result = await connector.run_command_as_su("echo ok", "pw", su_user="deploy")

    assert result.stdout == "ok"
    written = "".join(fake_conn.created_processes[0].stdin.written)
    assert "su - deploy\n" in written


@pytest.mark.asyncio
async def test_run_command_as_su_nonzero_exit_status_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        "Password: ",
        "root\n__SU_CHECK__:0\n",
        "__CMD_START__\nsome error output\n__CMD_END__:1\n",
    ]
    fake_conn = _FakeConnection(chunks)
    _patch_connect(monkeypatch, fake_conn)

    connector = SSHConnector(SSHTarget(host="fake-host"))
    result = await connector.run_command_as_su("false", "root-pw")

    assert result.exit_status == 1
    assert result.ok is False
    assert result.stdout == "some error output"


@pytest.mark.asyncio
async def test_run_command_as_su_raises_when_remote_closes_before_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비밀번호 프롬프트를 기다리는 중 원격이 스트림을 끊으면(EOF, 예:
    비밀번호 프롬프트 문구가 예상과 달라 매칭에 실패하고 쉘이 종료된 경우)
    무한 대기 대신 즉시 명확한 에러로 실패해야 한다."""
    fake_conn = _FakeConnection([])  # 아무 출력도 없이 바로 EOF
    _patch_connect(monkeypatch, fake_conn)

    connector = SSHConnector(SSHTarget(host="fake-host"), connect_timeout=0.05)

    with pytest.raises(RuntimeError, match="연결이 끊김"):
        await connector.run_command_as_su("echo hi", "root-pw")


@pytest.mark.asyncio
async def test_run_command_as_su_times_out_when_prompt_never_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """원격이 연결은 유지한 채(EOF 없이) 그냥 프롬프트를 영원히 안 보내는
    경우(예: 방화벽에 막혀 응답이 느린 경우)도 무한 대기 대신 타임아웃으로
    실패해야 한다."""

    class _HangingStdout:
        async def read(self, n: int = -1) -> str:
            await asyncio.sleep(3600)
            return ""

    class _HangingProcess:
        def __init__(self) -> None:
            self.stdin = _FakeStdin()
            self.stdout = _HangingStdout()

        def terminate(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    class _HangingConnection:
        def is_closed(self) -> bool:
            return False

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

        async def create_process(self, **kwargs: object) -> _HangingProcess:
            return _HangingProcess()

    async def _fake_connect(**kwargs: object) -> _HangingConnection:
        return _HangingConnection()

    monkeypatch.setattr(ssh_client_module.asyncssh, "connect", _fake_connect)

    connector = SSHConnector(SSHTarget(host="fake-host"), connect_timeout=0.05, close_timeout=0.05)

    with pytest.raises(TimeoutError, match="대기 타임아웃"):
        await connector.run_command_as_su("echo hi", "root-pw")
