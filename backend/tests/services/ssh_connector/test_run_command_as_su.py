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


@pytest.mark.asyncio
async def test_run_command_as_su_ignores_echoed_command_text_before_real_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실 서버 재현 버그(2026-07-30): `su - root`가 새 로그인 쉘을 띄우면서 그
    쉘의 시작 스크립트(`.bashrc` 등)가 로컬 에코를 다시 켜는 환경이 있었다.
    그러면 `stty -echo`가 이미 무력화된 상태라, 우리가 stdin에 쓴 명령 문자열
    자체("...echo __SU_CHECK__:$?" 같은 *글자 그대로*)가 먼저 그대로
    되읽힌다 — `$?`가 실제 평가되기 전이라 마커 뒤에 숫자가 없다. 이 echo된
    입력 한 조각만 먼저 도착하고, 진짜 실행 결과(숫자가 붙은 마커)는 그다음
    청크에야 온다 — 실제로 이 순서로 재현해서 회귀를 잡는다. (버그 당시엔
    `__SU_CHECK__:` 부분 문자열 매칭이라 echo된 줄만 보고 "명령이 끝났다"고
    착각해 `su - root 인증 실패로 보임` 오류를 냈다.)
    """
    chunks = [
        "Password: ",
        # su 성공 직후: 로그인 배너 + 프롬프트 + "우리가 입력한 그대로"의 에코
        # (実 서버 캡처와 동일한 모양, $?가 아직 평가되지 않은 문자 그대로).
        "\r\nLast login: Thu Jul 30 09:39:22 KST 2026 on pts/1\r\n"
        "host [root{997} ~ ] whoami; echo __SU_CHECK__:$?\r\n",
        # 그다음 청크에야 실제 실행 결과(숫자 붙은 마커)가 도착한다.
        "root\r\n__SU_CHECK__:0\r\nhost [root{997} ~ ] ",
        "echo __CMD_START__; echo hello world; echo __CMD_END__:$?\r\n",
        "__CMD_START__\r\nhello world\r\n__CMD_END__:0\r\n",
    ]
    fake_conn = _FakeConnection(chunks)
    _patch_connect(monkeypatch, fake_conn)

    connector = SSHConnector(SSHTarget(host="fake-host"))
    result = await connector.run_command_as_su("echo hello world", "root-pw")

    assert result.exit_status == 0
    assert result.stdout == "hello world"
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
