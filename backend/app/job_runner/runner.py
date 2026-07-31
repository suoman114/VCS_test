"""비동기 Test Run Job 관리 골격.

`pending -> running -> parsing -> done/failed/error` 상태 전이를 관리한다.
초기엔 `asyncio.create_task` 기반 자체 Job Runner이며, 동시 실행 시험이
늘어나면 Celery/Redis 큐로 교체 가능하도록 이 모듈만 바뀌면 되게 분리했다
(CLAUDE.md §4).

실제 실행 로직(설정 파일 전송, vctp 재기동, SIPp 트리거 등)은 이 모듈이
알지 못한다 — `TestExecutor.run()` 구현체(다음 웨이브)가 job_runner를
호출해서 상태를 갱신하는 방향으로 조립한다.

다른 에이전트 사용법:
    from app.job_runner import job_runner, JobRunner
    from app.models.test_run import TestRunStatus

    task = job_runner.submit(run_id, lambda: my_executor_coroutine(test_case))
    await job_runner.set_status(run_id, TestRunStatus.RUNNING)
    ...
    await job_runner.set_status(run_id, TestRunStatus.DONE, result_summary="...")
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from app.core.database import SessionLocal
from app.models.test_run import TestRun, TestRunStatus

logger = logging.getLogger(__name__)

JobFactory = Callable[[], Awaitable[None]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobRunner:
    """TestRun 단위 asyncio.Task 생명주기 + 상태 전이 관리자."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def submit(self, run_id: str, job_factory: JobFactory) -> asyncio.Task[None]:
        """run_id에 대한 job 코루틴을 asyncio.Task로 스케줄링한다.

        job_factory는 인자 없이 호출 가능한 코루틴 팩토리(보통
        `functools.partial(executor.run, test_case)`의 래퍼)여야 한다.
        동일 run_id가 이미 실행 중이면 예외를 발생시킨다.
        """
        existing = self._tasks.get(run_id)
        if existing is not None and not existing.done():
            raise RuntimeError(f"Job for run_id={run_id!r} is already running")

        task = asyncio.create_task(self._run_wrapper(run_id, job_factory), name=f"test-run-{run_id}")
        self._tasks[run_id] = task
        return task

    async def _run_wrapper(self, run_id: str, job_factory: JobFactory) -> None:
        try:
            await job_factory()
        except asyncio.CancelledError:
            logger.info("Job %s was cancelled", run_id)
            await self.set_status(run_id, TestRunStatus.ERROR, result_summary=json.dumps({"error": "cancelled"}))
            raise
        except Exception as exc:  # noqa: BLE001 - 실행기 예외를 ERROR 상태로 수렴시킴
            logger.exception("Job %s raised an unhandled exception", run_id)
            # 실행기가 던진 예외 메시지(예: protocol_params 필수값 누락, SSH 연결
            # 실패 등)를 result_summary에 남긴다 — 그동안 backend.log에만 남고
            # 대시보드 어디에도 안 보여서, 시험 케이스 설정 실수 하나 확인하려고
            # 서버에 SSH로 접속해 로그를 뒤져야 했다(2026-07-30 실 사용 중 확인).
            await self.set_status(
                run_id, TestRunStatus.ERROR, result_summary=json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            )

    def get_task(self, run_id: str) -> asyncio.Task[None] | None:
        return self._tasks.get(run_id)

    async def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

    @staticmethod
    async def set_status(run_id: str, status: TestRunStatus, **fields: Any) -> None:
        """TestRun 상태 및 부가 필드를 DB에 반영한다.

        VoLTE/McPTT executor, log-collector-agent 등이 상태를 갱신할 때 쓰는
        공용 진입점. fields로 raw_log_path, result_summary, target_host 등을
        함께 갱신할 수 있다.
        """

        def _update() -> None:
            db = SessionLocal()
            try:
                run = db.get(TestRun, run_id)
                if run is None:
                    logger.warning("set_status: TestRun %s not found", run_id)
                    return
                run.status = status
                for key, value in fields.items():
                    setattr(run, key, value)
                if status == TestRunStatus.RUNNING and run.started_at is None:
                    run.started_at = _utcnow()
                if status in (TestRunStatus.DONE, TestRunStatus.FAILED, TestRunStatus.ERROR):
                    run.ended_at = _utcnow()
                db.commit()
            finally:
                db.close()

        await asyncio.to_thread(_update)


job_runner = JobRunner()
