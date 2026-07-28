"""SSH/SCP 공통 클라이언트 (asyncssh 기반).

자격증명은 항상 Settings(환경변수)에서만 읽는다. volte/mcptt executor와
log-collector-agent가 이 클래스를 공용으로 재사용한다.

다른 에이전트 사용법 요약:
    connector = SSHConnector()  # 기본값: VCS 접속 정보 (settings.vcs_ssh_*)
    result = await connector.run_command("systemctl restart vctp")
    await connector.upload_file(local_path, remote_path)
    async for line in connector.tail_file("/var/log/vcs/vctp.log"):
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
        self, command: str, *, timeout: float | None = None, check: bool = False
    ) -> CommandResult:
        """원격 커맨드를 한 번 실행하고 결과를 반환한다.

        VoLTE executor가 `vctp` 재기동 명령을 실행하는 데 사용할 인터페이스.
        실제 명령 문자열은 CLAUDE.md §13 TBD 확정 후 volte executor에서 채운다.
        """
        conn = await self.connect()
        result = await conn.run(command, check=check, timeout=timeout)
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
        """
        conn = await self.connect()
        tail_args = "-F -n +1" if from_beginning else "-F"
        process = await conn.create_process(f"tail {tail_args} {remote_path}")
        try:
            assert process.stdout is not None
            async for line in process.stdout:
                yield line.rstrip("\n")
                if stop_event is not None and stop_event.is_set():
                    break
        finally:
            process.terminate()
            await process.wait_closed()
