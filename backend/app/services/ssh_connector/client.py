"""SSH/SCP 공통 클라이언트 (asyncssh 기반).

자격증명은 항상 Settings(환경변수)에서만 읽는다. volte/mcptt executor와
log-collector-agent가 이 클래스를 공용으로 재사용한다.

다른 에이전트 사용법 요약:
    connector = SSHConnector()  # 기본값: VCS 접속 정보 (settings.vcs_ssh_*)
    result = await connector.run_command("stopmc -b vctp")
    await connector.upload_file(local_path, remote_path)
    async for line in connector.tail_file("/home/vcs/vcsm/logs/vcsm.log"):
        ...
    await connector.close()

원격 대상이 여러 개(VCS / SIPp 전용 호스트)일 수 있으므로, 호스트 정보를
직접 주입해 재사용할 수 있도록 `SSHTarget`도 함께 제공한다.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import asyncssh

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SSHTarget:
    """접속 대상 호스트 정보. 기본값은 Settings의 VCS 접속 정보."""

    host: str
    port: int = 22
    username: str | None = None
    password: str | None = None
    private_key_path: str | None = None
    known_hosts: str | None = None

    @classmethod
    def from_vcs_settings(cls, settings: Settings | None = None) -> "SSHTarget":
        s = settings or get_settings()
        if not s.vcs_ssh_host:
            raise ValueError("VCS_SSH_HOST가 설정되지 않았다 (.env 확인)")
        return cls(
            host=s.vcs_ssh_host,
            port=s.vcs_ssh_port,
            username=s.vcs_ssh_username,
            password=s.vcs_ssh_password,
            private_key_path=s.vcs_ssh_private_key_path,
            known_hosts=s.vcs_ssh_known_hosts,
        )

    @classmethod
    def from_sipp_settings(cls, settings: Settings | None = None) -> "SSHTarget":
        s = settings or get_settings()
        if not s.sipp_ssh_host:
            raise ValueError("SIPP_SSH_HOST가 설정되지 않았다 (.env 확인)")
        return cls(
            host=s.sipp_ssh_host,
            port=s.sipp_ssh_port,
            username=s.sipp_ssh_username,
            password=s.sipp_ssh_password,
            private_key_path=s.sipp_ssh_private_key_path,
            known_hosts=None,
        )


@dataclass
class CommandResult:
    command: str
    exit_status: int | None
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


class SSHConnector:
    """단일 SSHTarget에 대한 연결을 재사용하는 비동기 SSH/SCP 클라이언트."""

    def __init__(
        self,
        target: SSHTarget | None = None,
        *,
        connect_timeout: float | None = None,
        close_timeout: float | None = None,
    ) -> None:
        self._target = target or SSHTarget.from_vcs_settings()
        self._conn: asyncssh.SSHClientConnection | None = None
        self._lock = asyncio.Lock()
        settings = get_settings()
        self._connect_timeout = (
            connect_timeout if connect_timeout is not None else settings.vcs_ssh_connect_timeout_sec
        )
        self._close_timeout = close_timeout if close_timeout is not None else settings.vcs_ssh_close_timeout_sec

    async def __aenter__(self) -> "SSHConnector":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def connect(self) -> asyncssh.SSHClientConnection:
        async with self._lock:
            if self._conn is None or self._conn.is_closed():
                client_keys = [self._target.private_key_path] if self._target.private_key_path else None
                known_hosts = self._target.known_hosts if self._target.known_hosts else None
                logger.info("Connecting to SSH target %s:%s", self._target.host, self._target.port)
                try:
                    self._conn = await asyncio.wait_for(
                        asyncssh.connect(
                            host=self._target.host,
                            port=self._target.port,
                            username=self._target.username,
                            password=self._target.password or None,
                            client_keys=client_keys,
                            known_hosts=known_hosts,
                        ),
                        timeout=self._connect_timeout,
                    )
                except TimeoutError as exc:
                    # asyncssh의 login_timeout(기본 120초)은 TCP 연결이 이미 수립된
                    # 뒤에야 시작된다 — TCP handshake 자체가 응답 없이 멈추는 경우
                    # (네트워크 순단 등)는 보호되지 않아 이 호출이 영원히 멈출 수
                    # 있었다. 실 서버에서 SSH tail 재연결이 예외/로그 하나 없이
                    # 조용히 멈추고, CollectorSession.stop()이 그 태스크를 영원히
                    # 기다리며 TestRun이 "running"에서 멈추는 장애로 관찰됐다.
                    logger.error(
                        "Connecting to SSH target %s:%s timed out after %.1fs",
                        self._target.host,
                        self._target.port,
                        self._connect_timeout,
                    )
                    raise TimeoutError(
                        f"SSH connect to {self._target.host}:{self._target.port} timed out"
                        f" after {self._connect_timeout}s"
                    ) from exc
            return self._conn

    async def close(self) -> None:
        if self._conn is not None and not self._conn.is_closed():
            self._conn.close()
            try:
                await asyncio.wait_for(self._conn.wait_closed(), timeout=self._close_timeout)
            except TimeoutError:
                logger.warning(
                    "SSH connection to %s:%s did not confirm close within %.1fs — abandoning wait",
                    self._target.host,
                    self._target.port,
                    self._close_timeout,
                )
        self._conn = None

    async def run_command(
        self,
        command: str,
        *,
        timeout: float | None = None,
        check: bool = False,
        request_pty: bool = True,
    ) -> CommandResult:
        """원격 커맨드를 한 번 실행하고 결과를 반환한다.

        VoLTE executor의 `vctp` 재기동/`sed`, McPTT의 원격 SIPp 실행, 샘플 파일
        목록 조회(`ls`)까지 전부 이 함수를 통해 실행된다.

        `request_pty=True`(기본값)로 pseudo-terminal을 요청한다: SSH `exec`
        채널은 서버가 접속 계정의 로그인 셸(`/etc/passwd`)로 명령을 감싸 실행하는데,
        VCS `vcs` 계정의 로그인 셸은 `/bin/bash`이고(실 서버에서 `echo $SHELL`로
        확인, `.cshrc`는 애초에 존재하지 않음 — 초기에 csh/tcsh로 추정했던 건
        틀렸다) 시작 스크립트 어딘가가 tty 없는 비대화형 세션에서 `stty:
        standard input: Inappropriate ioctl for device`로 실패해 원래 명령의
        정상 출력을 가려버렸다. pty를 요청하면 `stty`가 정상적인 pty를 보고
        조용히 성공하므로 이 문제가 사라진다.

        `term_type`은 실제 터미널처럼 보이는 값("xterm")을 쓴다("dumb"으로
        시도했다가 별 효과가 없어 변경). `term_size`도 명시적으로 80x24로
        준다 — asyncssh는 명시하지 않으면 pty를 0x0 크기로 요청한다(소스 확인,
        `SSHClientChannel._send_pty_request`).

        `errors="replace"`도 필수다: asyncssh는 기본적으로 원격 출력을 UTF-8로
        엄격하게(`errors="strict"`) 디코딩하는데, pcap 샘플 파일명 중 일부가
        EUC-KR 등 비-UTF-8 인코딩이라 디코딩이 실패하면 **해당 세션 하나가
        아니라 SSH 커넥션 전체가 그 자리에서 강제 종료**된다(실 서버에서
        `MSG_DISCONNECT` + `'utf-8' codec can't decode byte ...` 확인). 그
        결과 이미 받은 출력 전체가 버려지고 exit_status=0(디코딩 실패 전에
        받은 exit-status)에 stdout/stderr만 텅 빈 것처럼 보였다 — `ls` 등
        모든 원격 명령이 비-ASCII 파일명/로그를 만나면 이렇게 조용히 깨질 수
        있는 심각한 문제였다. `errors="replace"`로 깨진 바이트만 U+FFFD로
        대체하고 연결은 살려둔다.
        """
        conn = await self.connect()
        term_type = "xterm" if request_pty else None
        term_size = (80, 24) if request_pty else None
        result = await conn.run(
            command,
            check=check,
            timeout=timeout,
            term_type=term_type,
            term_size=term_size,
            errors="replace",
        )
        return CommandResult(
            command=command,
            exit_status=result.exit_status,
            stdout=str(result.stdout) if result.stdout is not None else "",
            stderr=str(result.stderr) if result.stderr is not None else "",
        )

    async def run_command_as_su(
        self,
        command: str,
        su_password: str,
        *,
        su_user: str = "root",
        timeout: float | None = None,
    ) -> CommandResult:
        """로그인 계정(예: sysadm)으로 접속한 뒤 `su - {su_user}`로 전환해서
        명령을 실행한다.

        일부 배포 환경은 root 직접 SSH 로그인을 막아놔서(`PermitRootLogin no`)
        일반 계정으로 먼저 접속한 뒤 `su`로 전환해야 한다(2026-07-29, McPTT
        SIPp 전용 호스트 요구사항). `su`는 보안상 비밀번호를 stdin 파이프로
        받지 않고 항상 제어 터미널(tty)에서만 읽으므로, `run_command()`처럼
        `conn.run()`으로 한 번에 실행할 수 없다 — 대신 PTY 위에 인터랙티브
        쉘을 띄우고 `su`의 비밀번호 프롬프트에 직접 응답하는 방식으로
        구현한다. PTY를 쓰면 stdin에 쓴 데이터가 곧 "터미널에 입력한 것"과
        동일하게 취급되므로 이 방식이 통한다.

        먼저 `stty -echo`로 로컬 에코를 꺼서 출력 스트림 노이즈를 줄이지만,
        `su - {su_user}`가 새 로그인 쉘을 띄우면서 그 쉘의 시작 스크립트가
        (`.bashrc` 등에서 `stty sane`류 호출로) 에코를 다시 켜는 경우가
        실 서버에서 확인됐다(2026-07-30). 그러면 우리가 방금 stdin에 쓴
        명령 문자열 자체가 그대로 되읽혀서(예: `echo __CMD_END__:$?`라는
        *글자 그대로의 문자열*), `$?`가 실제 평가되기도 전에 마커 문자열이
        먼저 출력 스트림에 나타난다 — 마커를 단순 부분 문자열로 찾으면 이
        echo된 입력 자체를 "명령이 끝났다"는 신호로 착각해 응답을 너무
        일찍 끊어버린다. 그래서 마커는 항상 **"마커:숫자"** 형태(`$?`가
        실제로 셸에 의해 평가된 결과)로만 매칭한다 — 우리가 타이핑한
        문자열에는 `$?`가 문자 그대로 남아있어 숫자가 뒤따르지 않으므로,
        이 정규식은 echo된 입력과 절대 매치되지 않는다.

        `su` 성공 여부는 비밀번호 입력 직후 `whoami`를 실행해 `su_user`가
        나오는지로 확인한다(실패하면 여전히 원래 계정인 채로 프롬프트만
        다시 나타나는 경우가 많아, exit code만으로는 판단하기 어렵다).

        **주의**: 이 로직은 실 서버 su 프롬프트로 검증했다(2026-07-30,
        마커 오탐 버그를 이 방식으로 수정) — 다만 모든 셸/로케일 조합까지
        전부 확인하지는 못했다. 프롬프트 문구가 예상과 다르면(예:
        "Password:"가 아닌 다른 언어) 여전히 실패할 수 있다.
        """
        conn = await self.connect()
        process = await conn.create_process(term_type="xterm", term_size=(80, 24), errors="replace")
        op_timeout = timeout if timeout is not None else self._connect_timeout
        assert process.stdin is not None and process.stdout is not None

        buf = ""

        async def read_until(pattern: str, read_timeout: float, *, is_regex: bool = False) -> str:
            nonlocal buf
            matched = (lambda: re.search(pattern, buf)) if is_regex else (lambda: pattern in buf)
            deadline = asyncio.get_event_loop().time() + read_timeout
            while not matched():
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise TimeoutError(
                        f"su_user={su_user!r} 전환 중 {pattern!r} 대기 타임아웃"
                        f" (누적 출력 마지막 500자: {buf[-500:]!r})"
                    )
                try:
                    chunk = await asyncio.wait_for(process.stdout.read(4096), timeout=remaining)
                except TimeoutError as exc:
                    raise TimeoutError(
                        f"su_user={su_user!r} 전환 중 {pattern!r} 대기 타임아웃"
                        f" (누적 출력 마지막 500자: {buf[-500:]!r})"
                    ) from exc
                if not chunk:
                    raise RuntimeError(
                        f"su_user={su_user!r} 전환 중 원격 쉘 연결이 끊김"
                        f" (누적 출력 마지막 500자: {buf[-500:]!r})"
                    )
                buf += chunk
            return buf

        try:
            process.stdin.write("stty -echo\n")
            await process.stdin.drain()

            process.stdin.write(f"su - {su_user}\n")
            await process.stdin.drain()
            await read_until("assword", op_timeout)  # "Password:"/"암호:" 등 대소문자·언어 무관 매칭
            buf = ""

            process.stdin.write(f"{su_password}\n")
            await process.stdin.drain()
            process.stdin.write("whoami; echo __SU_CHECK__:$?\n")
            await process.stdin.drain()
            # "__SU_CHECK__:" 뒤에 숫자가 와야만 진짜 실행 결과다(위 docstring 참고).
            su_check_output = await read_until(r"__SU_CHECK__:\d", op_timeout, is_regex=True)
            if not re.search(r"__SU_CHECK__:0\b", su_check_output) or su_user not in su_check_output:
                raise RuntimeError(
                    f"su - {su_user} 인증 실패로 보임"
                    f" (출력 마지막 300자: {su_check_output[-300:]!r})"
                )
            buf = ""

            process.stdin.write(f"echo __CMD_START__; {command}; echo __CMD_END__:$?\n")
            await process.stdin.drain()
            cmd_output = await read_until(r"__CMD_END__:\d", op_timeout, is_regex=True)

            start_idx = cmd_output.rfind("__CMD_START__")
            body = cmd_output[start_idx + len("__CMD_START__") :] if start_idx >= 0 else cmd_output
            end_idx = body.rfind("__CMD_END__:")
            stdout_text = body[:end_idx].strip("\r\n") if end_idx >= 0 else body.strip("\r\n")
            trailer = body[end_idx + len("__CMD_END__:") :] if end_idx >= 0 else ""
            exit_token = trailer.strip().split()[0] if trailer.strip() else ""
            try:
                exit_status = int(exit_token)
            except ValueError:
                exit_status = None

            return CommandResult(command=command, exit_status=exit_status, stdout=stdout_text, stderr="")
        finally:
            process.stdin.write("exit\n")  # su 쉘 종료
            process.stdin.write("exit\n")  # 로그인 쉘 종료
            process.terminate()
            try:
                await asyncio.wait_for(process.wait_closed(), timeout=self._close_timeout)
            except TimeoutError:
                logger.warning(
                    "run_command_as_su: process did not confirm close within %.1fs — abandoning wait",
                    self._close_timeout,
                )

    async def upload_file(self, local_path: str | Path, remote_path: str) -> None:
        """SCP/SFTP로 로컬 파일을 원격 경로에 업로드한다 (VoLTE 설정 파일 적용용)."""
        conn = await self.connect()
        async with conn.start_sftp_client() as sftp:
            await sftp.put(str(local_path), remote_path)

    async def download_file(self, remote_path: str, local_path: str | Path) -> None:
        conn = await self.connect()
        async with conn.start_sftp_client() as sftp:
            await sftp.get(remote_path, str(local_path))

    async def tail_file(
        self,
        remote_path: str,
        *,
        from_beginning: bool = False,
        stop_event: asyncio.Event | None = None,
    ) -> AsyncIterator[str]:
        """원격 파일을 `tail -F`로 실시간 스트리밍하는 비동기 제너레이터.

        log-collector-agent가 이 제너레이터를 소비해 원본 로그 파일에 append하고
        WebSocket(ws.manager.broadcast_to_run)으로 동시에 브로드캐스트한다.
        `stop_event`가 set되면 다음 라인 수신 후 스트림을 종료한다.

        `errors="replace"`: VCS 로그에 비-UTF-8 바이트(예: 완성형 인코딩의
        한글)가 섞여 있으면 asyncssh가 기본 UTF-8 strict 디코딩에 실패해
        SSH 커넥션 전체를 끊어버리는 문제가 있다(`run_command` 문서 참고,
        pcap 샘플명 조회에서 실 서버로 확인됨). 로그 tail에서 이 문제가
        나면 스트리밍 전체가 끊기므로 반드시 `errors="replace"`가 필요하다.

        pty도 `run_command`와 동일하게 요청한다(`term_type="xterm"`,
        `term_size=(80, 24)`) — 이 함수는 그동안 pty 없이 실행하고 있었는데,
        `run_command`를 깨뜨렸던 것과 같은 부류의 셸 시작 스크립트 문제가
        여기도 그대로 남아있어 tail 세션이 예기치 않게 끊기고
        `SshTailSource`의 재연결 백오프(최대 30초) 동안 로그가 멈추는
        것처럼 보였을 수 있다.

        `finally`의 `process.wait_closed()`에도 타임아웃을 건다: `terminate()`는
        TERM 신호만 보내고 바로 리턴되지만, 그 뒤 원격이 채널 종료를
        확인(`Received channel close`)해줄 때까지 기다리는 `wait_closed()`엔
        원래 타임아웃이 없었다. 실 서버에서 tail 채널 3개 모두 TERM 신호까지는
        로그가 남는데 그 뒤로 채널 종료 확인이 전혀 없이 조용히 멈추는 장애가
        확인됐다(2026-07-29) — `CollectorSession.stop()`이 이 지점에서 영원히
        `asyncio.gather`로 기다리게 되어 TestRun이 `running`에서 못 벗어났다.
        """
        conn = await self.connect()
        tail_args = "-F -n +1" if from_beginning else "-F"
        process = await conn.create_process(
            f"tail {tail_args} {remote_path}",
            errors="replace",
            term_type="xterm",
            term_size=(80, 24),
        )
        try:
            assert process.stdout is not None
            async for line in process.stdout:
                yield line.rstrip("\n")
                if stop_event is not None and stop_event.is_set():
                    break
        finally:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait_closed(), timeout=self._close_timeout)
            except TimeoutError:
                logger.warning(
                    "tail_file(%s): process did not confirm close within %.1fs — abandoning wait",
                    remote_path,
                    self._close_timeout,
                )
