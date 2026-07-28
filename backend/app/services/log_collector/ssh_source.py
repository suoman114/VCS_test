"""VCS 등 원격 서버의 로그 파일을 SSH `tail -F`로 실시간 수집하는 소스.

SSH 연결/명령 실행은 전부 backend-agent가 만든 `SSHConnector`를 그대로
재사용한다(재구현 금지, CLAUDE.md log-collector-agent 지침). 이 모듈은
그 위에 "연결 끊김 감지 + 지수 백오프 재연결" 정책만 얹는다.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from app.services.log_collector.base import LogSource, LogSourceError, RetryPolicy
from app.services.ssh_connector.client import SSHConnector, SSHTarget

logger = logging.getLogger(__name__)


class SshTailSource(LogSource):
    """SSH로 원격 파일을 `tail -F` 스트리밍하는 `LogSource` 구현체.

    사용 예 (VoLTE: vcsm.log/vcmm.log, McPTT: vcmc.log/vcmm.log — CLAUDE.md §3):
        source = SshTailSource(
            "vcsm_log", "/var/log/vcs/vcsm.log", target=SSHTarget.from_vcs_settings(),
        )
        async for line in source.stream(stop_event):
            ...

    연결이 끊기면(원격 프로세스 종료, 네트워크 단절 등) 새 `SSHConnector`로
    재연결을 시도한다. 재연결 시에는 `from_beginning`을 다시 적용하지
    않는다(처음 연결에서만 적용) — 그렇지 않으면 재연결마다 로그 전체를
    다시 읽어 중복 라인이 저장/브로드캐스트되기 때문이다.
    """

    def __init__(
        self,
        name: str,
        remote_path: str,
        *,
        target: SSHTarget | None = None,
        from_beginning: bool = False,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.name = name
        self._remote_path = remote_path
        self._target = target
        self._from_beginning = from_beginning
        self._retry_policy = retry_policy or RetryPolicy()

    async def stream(self, stop_event: asyncio.Event) -> AsyncIterator[str]:
        attempt = 0
        first_connect = True

        while not stop_event.is_set():
            connector = SSHConnector(self._target)
            try:
                async for line in connector.tail_file(
                    self._remote_path,
                    from_beginning=self._from_beginning and first_connect,
                    stop_event=stop_event,
                ):
                    attempt = 0
                    yield line
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 재연결 여부 판단을 위해 넓게 캐치
                logger.warning(
                    "SshTailSource(%s): tail stream error on %s (attempt=%d): %s",
                    self.name,
                    self._remote_path,
                    attempt + 1,
                    exc,
                )
            finally:
                await connector.close()

            first_connect = False
            if stop_event.is_set():
                return

            attempt += 1
            if attempt > self._retry_policy.max_retries:
                raise LogSourceError(
                    f"SshTailSource({self.name}): {self._remote_path}에 대한 tail 재연결이 "
                    f"{self._retry_policy.max_retries}회 연속 실패해 포기한다"
                )

            backoff = self._retry_policy.backoff_seconds(attempt)
            logger.info(
                "SshTailSource(%s): reconnecting to %s in %.1fs (attempt %d/%d)",
                self.name,
                self._remote_path,
                backoff,
                attempt,
                self._retry_policy.max_retries,
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff)
                return  # stop_event가 backoff 대기 중 set됨 -> 재연결 없이 종료
            except asyncio.TimeoutError:
                pass  # backoff 경과, 재연결 시도
