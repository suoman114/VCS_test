"""Test Run 단위로 여러 `LogSource`를 동시에 구독해 저장+스트리밍하는 세션.

CLAUDE.md §3.3 공통 실행 원칙: "실시간 로그는 수집되는 즉시 WebSocket으로
대시보드에 스트리밍한다 (저장과 스트리밍을 동시에, 수집 완료를 기다리지
않음)". 이 모듈이 그 원칙을 구현한다.

- 원본 로그는 `storage/logs/{test_case_id}/{run_id}/{source.name}.log`에
  라인 수신 즉시 append한다 (CLAUDE.md §3.3, §5).
- 동시에 `app.ws.manager.broadcast_to_run(run_id, ...)`으로 해당 run_id를
  구독 중인 WebSocket 클라이언트에 브로드캐스트한다.
- 로그 내용은 해석하지 않는다(원본 라인 그대로 저장/전달). 파싱은
  log-parser-callflow-agent 담당.

다른 에이전트(backend-agent) 사용 예:
    from app.services.log_collector import CollectorSession, CollectorSource, SshTailSource

    session = CollectorSession(
        run_id=test_run.id,
        test_case_id=test_case.id,
        sources=[
            CollectorSource(SshTailSource("vcsm_log", "/var/log/vcs/vcsm.log"), channel="vcs_log"),
            CollectorSource(SshTailSource("vcmm_log", "/var/log/vcs/vcmm.log"), channel="vcs_log"),
        ],
    )
    await session.start()
    ...  # vctp 재기동, 판정 대기 등 (backend-agent 담당)
    await session.stop()  # Test Run 종료 시 모든 소스 정리
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from app.core.config import Settings, get_settings
from app.services.log_collector.base import LogSource, LogSourceError
from app.ws.manager import manager

logger = logging.getLogger(__name__)


@dataclass
class CollectorSource:
    """`LogSource` + 대시보드 표시용 채널 태그.

    `channel`은 CLAUDE.md §8 "VCS 로그 / SIPp 로그 탭 구분"에 쓰이는 값으로,
    보통 `"vcs_log"` 또는 `"sipp_log"`를 쓴다. `source.name`은 개별 프로세스
    단위 식별자(예: `"vcsm_log"`, `"vcmm_log"`, `"sipp_log"`)이자 저장 파일명이다.
    """

    source: LogSource
    channel: str


class CollectorSession:
    """하나의 Test Run에 대한 다중 `LogSource` 구독/저장/브로드캐스트 세션."""

    def __init__(
        self,
        run_id: str,
        test_case_id: str,
        sources: list[CollectorSource],
        *,
        settings: Settings | None = None,
    ) -> None:
        self._run_id = run_id
        self._test_case_id = test_case_id
        self._sources = sources
        self._settings = settings or get_settings()
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._errors: dict[str, str] = {}
        self._started = False

    @property
    def run_dir(self) -> Path:
        """`storage/logs/{test_case_id}/{run_id}/` (CLAUDE.md §3.3, §5)."""
        return self._settings.log_storage_path / self._test_case_id / self._run_id

    @property
    def errors(self) -> dict[str, str]:
        """재시도 한도 초과 등으로 영구 실패한 소스 이름 -> 에러 메시지."""
        return dict(self._errors)

    @property
    def stop_event(self) -> asyncio.Event:
        return self._stop_event

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("CollectorSession already started")
        self._started = True
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._tasks = [
            asyncio.create_task(self._consume(cs), name=f"log-collect-{self._run_id}-{cs.source.name}")
            for cs in self._sources
        ]
        logger.info("CollectorSession started for run_id=%s with %d source(s)", self._run_id, len(self._sources))

    async def stop(self) -> None:
        """수집 중지를 요청하고 모든 소스 태스크가 정리될 때까지 대기한다.

        Test Run 종료(성공/실패/타임아웃 판정 완료) 시 backend-agent가 호출한다.
        """
        self._stop_event.set()
        await self.wait()
        logger.info("CollectorSession stopped for run_id=%s", self._run_id)

    async def wait(self) -> None:
        """모든 소스 태스크가 종료될 때까지 대기한다 (stop 요청은 별도)."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def __aenter__(self) -> "CollectorSession":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.stop()

    async def _consume(self, cs: CollectorSource) -> None:
        log_path = self.run_dir / f"{cs.source.name}.log"
        seq = 0
        try:
            async with aiofiles.open(log_path, "a", encoding="utf-8") as fh:
                async for line in cs.source.stream(self._stop_event):
                    seq += 1
                    await fh.write(line + "\n")
                    await fh.flush()
                    await manager.broadcast_to_run(self._run_id, self._log_message(cs, seq, line))
        except asyncio.CancelledError:
            raise
        except LogSourceError as exc:
            logger.error(
                "CollectorSession(%s): source %s failed permanently: %s", self._run_id, cs.source.name, exc
            )
            self._errors[cs.source.name] = str(exc)
            await manager.broadcast_to_run(self._run_id, self._error_message(cs, str(exc)))
        except Exception as exc:  # noqa: BLE001 - 소스별 예상 못한 예외를 세션 레벨 에러로 수렴
            logger.exception("CollectorSession(%s): unexpected error in source %s", self._run_id, cs.source.name)
            message = f"unexpected error: {exc}"
            self._errors[cs.source.name] = message
            await manager.broadcast_to_run(self._run_id, self._error_message(cs, message))

    def _log_message(self, cs: CollectorSource, seq: int, line: str) -> dict[str, Any]:
        """WebSocket으로 브로드캐스트하는 라인 단위 이벤트 스키마.

        {
            "type": "log",
            "run_id": "...",
            "channel": "vcs_log" | "sipp_log",
            "source": "vcsm_log",       # 소스 식별자 = 저장 파일명(확장자 제외)
            "seq": 1,                    # 이 소스 내 1부터 증가하는 시퀀스 번호
            "line": "<원본 로그 한 줄>",
            "ts": "2026-07-28T12:00:00.000000+00:00",
        }
        """
        return {
            "type": "log",
            "run_id": self._run_id,
            "channel": cs.channel,
            "source": cs.source.name,
            "seq": seq,
            "line": line,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    def _error_message(self, cs: CollectorSource, message: str) -> dict[str, Any]:
        """소스가 재시도 한도를 초과해 영구 실패했을 때의 이벤트 스키마.

        {
            "type": "log_source_error",
            "run_id": "...",
            "channel": "vcs_log",
            "source": "vcsm_log",
            "message": "SshTailSource(vcsm_log): ... 5회 연속 실패해 포기한다",
            "ts": "...",
        }
        """
        return {
            "type": "log_source_error",
            "run_id": self._run_id,
            "channel": cs.channel,
            "source": cs.source.name,
            "message": message,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
