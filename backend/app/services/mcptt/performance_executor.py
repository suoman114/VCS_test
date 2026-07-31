"""McPTT 성능 시험 실행기 (2026-07-30 추가, CLAUDE.md §7 "시험 유형" 축 확장).

기본 호처리(`McpttBasicCallExecutor`, `basic_call`)와 프로토콜(McPTT)은
같지만 시험 유형이 다르다 — 총 호 수(`-m`)만큼 돌고 자연 종료되는 게 아니라,
호 발생률(`-r`/`-rp`)로 무기한 호를 발생시키다가 **사용자가 명시적으로
종료해야 끝난다**(`POST /api/test-runs/{run_id}/cancel`, `job_runner.cancel`).
기존 basic_call 코드는 건드리지 않고 별도 실행기로 추가한다(CLAUDE.md §7 원칙).

절차:
    1. VCS측 로그(`vcmc.log`, `vcmm.log`) tail을 먼저 시작한다(basic_call과 동일).
    2. `protocol_params.call_rate`(필수)/`rate_period_ms`(기본 1000)로 시뮬레이터
       커맨드를 구성한다 — `build_mcptt_sim_args(..., call_rate=..., rate_period_ms=...)`.
    3. 로그를 주기적으로 재파싱해 Call Flow를 실시간 갱신하는 폴링 태스크를
       백그라운드로 띄우고, 그와 **동시에** 시뮬레이터 커맨드를 실행한다
       (basic_call은 "시뮬레이터 실행 -> 완료 대기"가 순차적이지만, 성능
       시험은 시뮬레이터 자체가 시험 기간 내내 도는 게 정상이라 동시 실행이
       필요하다).
    4. `protocol_params.max_duration_sec`가 있으면 그 시간 뒤 자동 종료(안전
       장치), 없으면 사용자가 "종료"하기 전까지 무기한 실행된다.
    5. 종료(자동/수동/취소) -> 원격 시뮬레이터 프로세스 실제 종료
       (`SSHConnector.run_command_cancellable`/`run_command_as_su`가 취소 시
       `process.terminate()`를 보장) -> 로그 tail 정리 -> CallEvent 저장 ->
       `performance_stats.compute_mcptt_performance_stats()`로 집계 ->
       `result_summary`에 저장. **사용자가 "종료" 버튼으로 멈춘 것은 정상
       완료로 취급한다**(`DONE`, `result_summary.stopped_by_user=true`) —
       실패가 아니다.

`TestCase.protocol_params` 키(기본 호처리와 공유하는 키는 그쪽 docstring
참고, `app/services/mcptt/executor.py`):
    call_rate (int, 필수)          : `-r` — rate_period_ms마다 이 횟수만큼 호 발생
    rate_period_ms (int, 기본 1000) : `-rp` — 밀리초 단위 주기 (1000 = 1초)
    max_duration_sec (float, 선택)  : 자동 종료 안전장치. 없으면 무기한(수동 종료 전까지)
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.job_runner import job_runner
from app.models.call_event import CallEvent
from app.models.test_run import TestRun, TestRunStatus
from app.services.execution_common import normalize_log_paths, parse_collected_logs, persist_call_flow, persist_results
from app.services.executor_base import TestCaseLike, TestExecutor, executor_registry
from app.services.log_collector import CollectorSession, CollectorSource, SshTailSource
from app.services.mcptt.executor import SippRunResult, build_mcptt_sim_args
from app.services.mcptt.performance_stats import compute_mcptt_performance_stats
from app.services.ssh_connector import SSHConnector, SSHTarget
from app.services.vcs_settings_store import resolve_sipp_root_password, resolve_sipp_target, resolve_vcs_target

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SEC = 2.0


def _default_ssh_connector_factory(target: SSHTarget) -> SSHConnector:
    return SSHConnector(target)


@executor_registry.register(protocol="mcptt", test_type="performance")
class McpttPerformanceExecutor(TestExecutor):
    """CLAUDE.md §7 McPTT 성능 시험 실행기 (`-r`/`-rp` 기반, 수동 종료)."""

    protocol = "mcptt"
    test_type = "performance"

    def __init__(
        self,
        run_id: str,
        *,
        settings: Settings | None = None,
        ssh_target_factory: Callable[[], SSHTarget] | None = None,
        sipp_ssh_target_factory: Callable[[], SSHTarget] | None = None,
        sipp_ssh_connector_factory: Callable[[SSHTarget], SSHConnector] | None = None,
        poll_interval_sec: float = _POLL_INTERVAL_SEC,
    ) -> None:
        super().__init__(run_id)
        self._settings = settings or get_settings()
        self._ssh_target_factory = ssh_target_factory or (lambda: resolve_vcs_target(self._settings))
        self._sipp_ssh_target_factory = sipp_ssh_target_factory or (
            lambda: resolve_sipp_target(self._settings)
        )
        self._sipp_ssh_connector_factory = sipp_ssh_connector_factory or _default_ssh_connector_factory
        self._poll_interval_sec = poll_interval_sec

    async def run(self, test_case: TestCaseLike) -> TestRun:
        run_id = self.run_id
        params: dict[str, Any] = dict(getattr(test_case, "protocol_params", {}) or {})
        target = self._ssh_target_factory()
        session: CollectorSession | None = None
        poll_task: asyncio.Task[list[CallEvent]] | None = None

        try:
            await job_runner.set_status(run_id, TestRunStatus.RUNNING, target_host=target.host)

            default_log_paths = {
                "vcmc_log": params.get("vcmc_log_path", self._settings.vcs_vcmc_log_path),
                "vcmm_log": params.get("vcmm_log_path", self._settings.vcs_vcmm_log_path),
            }
            extra_log_paths = normalize_log_paths(params.get("vcs_log_paths") or {})
            log_paths = {**default_log_paths, **extra_log_paths}
            sources = [
                CollectorSource(SshTailSource(name, path, target=target), channel="vcs_log")
                for name, path in log_paths.items()
            ]
            session = CollectorSession(
                run_id=run_id, test_case_id=test_case.id, sources=sources, settings=self._settings
            )
            await session.start()

            scenario_file = params.get("scenario_file") or test_case.config_ref
            if not scenario_file:
                raise ValueError(
                    "protocol_params.scenario_file(또는 config_ref)이 필요하다 —"
                    " GET /api/vcs/mcptt-scenario-files에서 조회한 파일명 중 하나를 지정해야 한다"
                )
            call_rate = params.get("call_rate")
            if call_rate is None:
                raise ValueError(
                    "protocol_params에 call_rate가 필요하다"
                    " (예: call_rate=1, rate_period_ms=1000 -> rate_period_ms마다 1콜씩, 즉 초당 1콜)"
                )
            rate_period_ms = params.get("rate_period_ms")

            sim_dir = params.get("mcptt_sim_dir", self._settings.mcptt_sim_dir)
            jar_name = params.get("mcptt_sim_jar_name", self._settings.mcptt_sim_jar_name)
            remote_scenario_path = PurePosixPath(sim_dir) / scenario_file
            jar_path = PurePosixPath(sim_dir) / jar_name

            # target_host/포트 기본값 로직은 McpttBasicCallExecutor와 동일
            # (VCS 접속 IP 자동 채움 + Settings 고정값, 2026-07-30 요청).
            sim_params: dict[str, Any] = dict(params)
            sim_params.setdefault("target_host", sim_params.get("target_ip") or target.host)
            sim_params.setdefault("target_port", self._settings.mcptt_sim_target_port)
            sim_params.setdefault("local_ip", self._settings.mcptt_sim_local_ip)
            sim_params.setdefault("local_port", self._settings.mcptt_sim_local_port)
            sim_params.setdefault("control_port", self._settings.mcptt_sim_control_port)
            argv = build_mcptt_sim_args(
                remote_scenario_path, sim_params, jar_path=str(jar_path), call_rate=call_rate,
                rate_period_ms=rate_period_ms,
            )

            max_duration_sec_raw = params.get("max_duration_sec")
            max_duration_sec = float(max_duration_sec_raw) if max_duration_sec_raw else None

            # 로그 재파싱 + Call Flow 실시간 갱신을 시뮬레이터 실행과 동시에 돌린다
            # (basic_call처럼 "실행 -> 완료 대기"로 순차 처리하면 안 된다 — 성능
            # 시험은 시뮬레이터 자체가 시험 기간 내내 도는 게 정상이다).
            stop_poll = asyncio.Event()
            poll_task = asyncio.create_task(
                self._poll_call_flow(session.run_dir, list(log_paths.keys()), run_id, stop_poll)
            )

            stopped_by_user = False
            sipp_result: SippRunResult | None = None
            started_at = time.monotonic()
            try:
                sipp_result = await self._run_sipp_remote(argv=argv, timeout_sec=max_duration_sec)
            except asyncio.CancelledError:
                # "종료" 버튼으로 job_runner.cancel()이 호출된 경우 — 성능 시험에서는
                # 정상적인 종료 방법이지 실패가 아니다. 여기서 흡수하고 정상 마무리로
                # 이어간다(재-raise하면 job_runner._run_wrapper가 ERROR로 덮어써버린다).
                stopped_by_user = True
                logger.info("McpttPerformanceExecutor(%s): stopped by user request", run_id)
            elapsed_sec = time.monotonic() - started_at

            stop_poll.set()
            events = await poll_task
            poll_task = None

            await session.stop()
            session = None

            await job_runner.set_status(
                run_id, TestRunStatus.PARSING, raw_log_path=str(self._run_dir_for(test_case.id, run_id))
            )
            # 반드시 persist_results() *전에* 통계를 계산한다 — persist_results가
            # events를 세션에 add()하고 commit()하면(expire_on_commit=True 기본값)
            # 그 세션이 close()된 뒤에는 이 객체들의 속성 접근이
            # DetachedInstanceError로 깨진다. persist_results 이후에는 이제
            # len(events)처럼 속성을 안 건드리는 연산만 안전하다.
            stats = compute_mcptt_performance_stats(events, elapsed_sec=elapsed_sec)
            await persist_results(run_id, events, protocol="mcptt")

            summary = json.dumps(
                {
                    "stopped_by_user": stopped_by_user,
                    "timed_out": (not stopped_by_user) and max_duration_sec is not None,
                    "call_rate": call_rate,
                    "rate_period_ms": rate_period_ms if rate_period_ms is not None else 1000,
                    "elapsed_sec": round(elapsed_sec, 1),
                    "event_count": len(events),
                    "sipp_exit_status": sipp_result.exit_status if sipp_result is not None else None,
                    **stats,
                }
            )
            await job_runner.set_status(run_id, TestRunStatus.DONE, result_summary=summary)
        finally:
            if poll_task is not None:
                poll_task.cancel()
            if session is not None:
                await session.stop()

        return await asyncio.to_thread(self._fetch_run, run_id)

    async def _poll_call_flow(
        self, run_dir: Path, log_names: list[str], run_id: str, stop_event: asyncio.Event
    ) -> list[CallEvent]:
        """`stop_event`가 set될 때까지 주기적으로 로그를 재파싱해 Call Flow를
        갱신하고, 마지막으로 한 번 더 파싱한 최종 이벤트 목록을 반환한다.

        basic_call의 `wait_for_completion`과 달리 pass_criteria 충족을
        기다리지 않는다 — 성능 시험은 "완료 조건"이 없고(무기한 실행) 사용자
        종료가 유일한 끝맺음이므로, 여기서는 순수하게 실시간 갱신만 한다.
        """
        events: list[CallEvent] = []
        while True:
            events = await asyncio.to_thread(parse_collected_logs, run_dir, log_names, run_id)
            await persist_call_flow(run_id, events, protocol="mcptt")
            if stop_event.is_set():
                return events
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval_sec)
            except asyncio.TimeoutError:
                pass

    async def _run_sipp_remote(self, *, argv: list[str], timeout_sec: float | None) -> SippRunResult:
        """SIPp 전용 원격 호스트에서 McPTT 시뮬레이터를 실행한다.

        기본 호처리의 `McpttBasicCallExecutor._run_sipp_remote`와 목적은
        같지만, 이쪽은 `timeout_sec=None`(무기한 실행)을 지원해야 하고 취소
        시 원격 프로세스를 실제로 죽여야 한다는 점이 다르다 — su 경로는
        `run_command_as_su`가 이미 `finally`에서 항상 `process.terminate()`를
        호출하도록 돼 있어 그대로 재사용하고(2026-07-30, `timeout=None`이
        로그인 프롬프트 타임아웃으로 조용히 캡핑되던 버그도 이번에 같이
        고쳤다), su가 아닌 경로는 `run_command()`(process 핸들이 없어
        취소해도 원격 프로세스가 안 죽을 수 있음) 대신 새로 추가한
        `run_command_cancellable()`을 쓴다.
        """
        target = self._sipp_ssh_target_factory()
        connector = self._sipp_ssh_connector_factory(target)
        root_password = resolve_sipp_root_password(self._settings)
        command = " ".join(shlex.quote(a) for a in argv)
        try:
            if root_password:
                result = await connector.run_command_as_su(command, root_password, timeout=timeout_sec)
            else:
                result = await connector.run_command_cancellable(command, timeout=timeout_sec)
        except TimeoutError:
            return SippRunResult(argv=argv, exit_status=None, stdout="", stderr="sipp process timed out (remote)")
        finally:
            await connector.close()
        return SippRunResult(argv=argv, exit_status=result.exit_status, stdout=result.stdout, stderr=result.stderr)

    def _run_dir_for(self, test_case_id: str, run_id: str) -> Path:
        return self._settings.log_storage_path / test_case_id / run_id

    @staticmethod
    def _fetch_run(run_id: str) -> TestRun:
        db = SessionLocal()
        try:
            run = db.get(TestRun, run_id)
            if run is None:
                raise LookupError(f"TestRun {run_id!r} not found after execution")
            db.expunge(run)
            return run
        finally:
            db.close()
