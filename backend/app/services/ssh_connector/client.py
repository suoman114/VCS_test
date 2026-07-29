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

    def __init__(self, target: SSHTarget | None = None) -> None:
        self._target = target or SSHTarget.from_vcs_settings()
        self._conn: asyncssh.SSHClientConnection | None = None
        self._lock = asyncio.Lock()

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
                self._conn = await asyncssh.connect(
                    host=self._target.host,
                    port=self._target.port,
                    username=self._target.username,
                    password=self._target.password or None,
                    client_keys=client_keys,
                    known_hosts=known_hosts,
                )
            return self._conn

    async def close(self) -> None:
        if self._conn is not None and not self._conn.is_closed():
            self._conn.close()
            await self._conn.wait_closed()
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
        """
        conn = await self.connect()
        tail_args = "-F -n +1" if from_beginning else "-F"
        process = await conn.create_process(
            f"tail {tail_args} {remote_path}", errors="replace"
        )
        try:
            assert process.stdout is not None
            async for line in process.stdout:
                yield line.rstrip("\n")
                if stop_event is not None and stop_event.is_set():
                    break
        finally:
            process.terminate()
            await process.wait_closed()
