"""로컬 파일시스템 로그(SIPp 등)를 `tail -f` 방식으로 폴링 수집하는 소스.

CLAUDE.md §13 TBD: SIPp가 자동화 서버 로컬에서 실행되는 경우, 그 로그
파일/csv를 이 소스로 폴링 수집한다. 이후 SIPp가 원격 전용 호스트에서
실행되는 것으로 확정되면 `SshTailSource`를 그대로 재사용하면 된다
(소스 어댑터 분리 원칙 — 이 경우 이 파일은 수정할 필요가 없다).
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles

from app.services.log_collector.base import LogSource, LogSourceError, RetryPolicy

logger = logging.getLogger(__name__)


class LocalFileSource(LogSource):
    """로컬 파일을 폴링 방식으로 tail하는 `LogSource` 구현체.

    사용 예:
        source = LocalFileSource("sipp_log", "/var/log/sipp/run123.log")
        async for line in source.stream(stop_event):
            ...

    파일이 아직 생성되지 않았으면(SIPp 프로세스 시작 직후 등) `RetryPolicy`에
    따라 대기하며, 읽기 도중 오류(예: 파일 회전/삭제)가 나면 같은 정책으로
    재오픈을 시도한다. 두 경우 모두 재시도 한도를 초과하면 `LogSourceError`를
    raise한다.
    """

    def __init__(
        self,
        name: str,
        file_path: str | Path,
        *,
        from_beginning: bool = True,
        poll_interval: float = 0.5,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.name = name
        self._path = Path(file_path)
        self._from_beginning = from_beginning
        self._poll_interval = poll_interval
        self._retry_policy = retry_policy or RetryPolicy()

    async def stream(self, stop_event: asyncio.Event) -> AsyncIterator[str]:
        if await self._wait_for_file(stop_event):
            return  # stop 요청됨 (파일 미생성 상태에서 중단)

        attempt = 0
        while not stop_event.is_set():
            try:
                async for line in self._read_from(self._path, stop_event):
                    attempt = 0
                    yield line
                return  # stop_event가 set되어 정상 종료
            except asyncio.CancelledError:
                raise
            except LogSourceError:
                raise
            except Exception as exc:  # noqa: BLE001 - 재오픈 여부 판단을 위해 넓게 캐치
                attempt += 1
                logger.warning(
                    "LocalFileSource(%s): read error on %s (attempt=%d): %s",
                    self.name,
                    self._path,
                    attempt,
                    exc,
                )
                if attempt > self._retry_policy.max_retries:
                    raise LogSourceError(
                        f"LocalFileSource({self.name}): {self._path} 읽기가 "
                        f"{self._retry_policy.max_retries}회 연속 실패해 포기한다"
                    ) from exc
                if await self._interruptible_sleep(stop_event, self._retry_policy.backoff_seconds(attempt)):
                    return

    async def _wait_for_file(self, stop_event: asyncio.Event) -> bool:
        """파일이 생성될 때까지 대기한다. stop_event가 먼저 set되면 True 반환."""
        attempt = 0
        while not self._path.exists():
            if stop_event.is_set():
                return True
            attempt += 1
            if attempt > self._retry_policy.max_retries:
                raise LogSourceError(
                    f"LocalFileSource({self.name}): {self._path} 파일이 "
                    f"{self._retry_policy.max_retries}회 재시도 후에도 생성되지 않았다"
                )
            if await self._interruptible_sleep(stop_event, self._retry_policy.backoff_seconds(attempt)):
                return True
        return False

    async def _read_from(self, path: Path, stop_event: asyncio.Event) -> AsyncIterator[str]:
        async with aiofiles.open(path, "r", encoding="utf-8", errors="replace") as fh:
            if not self._from_beginning:
                await fh.seek(0, os.SEEK_END)
            while not stop_event.is_set():
                line = await fh.readline()
                if line:
                    yield line.rstrip("\n")
                    continue
                if await self._interruptible_sleep(stop_event, self._poll_interval):
                    return

    @staticmethod
    async def _interruptible_sleep(stop_event: asyncio.Event, timeout: float) -> bool:
        """stop_event가 set되면 즉시(대기 없이) True, 아니면 timeout 경과 후 False."""
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
