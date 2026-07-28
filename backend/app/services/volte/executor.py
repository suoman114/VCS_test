"""VoLTE 기본 호처리 시험 실행기 (CLAUDE.md §3.1).

절차:
    1. `TestCase.config_ref`(저장소 루트 기준 상대 경로)의 설정 파일을
       SSH/SCP로 VCS의 `protocol_params["dest_path"]`에 업로드한다.
    2. SSH로 `protocol_params["restart_cmd"]`를 실행해 `vctp`를 재기동한다
       (정확한 명령은 CLAUDE.md §13 TBD — TestCase에서 주입받는 값 그대로
       실행할 뿐 하드코딩하지 않는다).
    3. `protocol_params["vcs_log_paths"]`에 명시된 로그 파일들을
       `CollectorSession`으로 실시간 tail 수집 시작.
    4. `pass_criteria` 충족 또는 `protocol_params["timeout_sec"]` 타임아웃까지
       주기적으로 재파싱하며 대기.
    5. 수집 종료 -> CallEvent 저장 -> Call Flow(Mermaid) 생성 -> 최종 상태
       (`done`/`failed`) 반영.

`TestCase.protocol_params` 키(요구 사항, 완료 보고 참고):
    dest_path (str, 필수)            : 설정 파일을 업로드할 VCS 내 목적지 경로
    restart_cmd (str, 필수)          : vctp 재기동 명령 (TBD, 그대로 실행)
    wait_after_restart_sec (float)   : 재기동 후 로그 수집 시작 전 대기(기본 0)
    vcs_log_paths (list[str] | dict) : tail 대상 로그 경로들
                                       (list면 파일명 stem 기준 자동 명명,
                                       예: "/var/log/vcs/vcsm.log" -> "vcsm_log")
    timeout_sec (float)              : 완료 판정 타임아웃(기본 30초)
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.job_runner import job_runner
from app.models.test_run import TestRun, TestRunStatus
from app.services.execution_common import normalize_log_paths, persist_results, wait_for_completion
from app.services.executor_base import TestCaseLike, TestExecutor, executor_registry
from app.services.log_collector import CollectorSession, CollectorSource, SshTailSource
from app.services.ssh_connector import SSHConnector, SSHTarget

logger = logging.getLogger(__name__)

SSHConnectorFactory = Callable[[SSHTarget], SSHConnector]


def _default_ssh_connector_factory(target: SSHTarget) -> SSHConnector:
    return SSHConnector(target)


@executor_registry.register(protocol="volte", test_type="basic_call")
class VolteBasicCallExecutor(TestExecutor):
    """CLAUDE.md §3.1 VoLTE 기본 호처리 시험 실행기."""

    protocol = "volte"
    test_type = "basic_call"

    def __init__(
        self,
        run_id: str,
        *,
        settings: Settings | None = None,
        ssh_target_factory: Callable[[], SSHTarget] | None = None,
        ssh_connector_factory: SSHConnectorFactory | None = None,
    ) -> None:
        """`ssh_target_factory`/`ssh_connector_factory`는 QA/Integration Agent가
        실제 SSH 연결 없이 모킹할 수 있도록 열어둔 의존성 주입 지점이다.
        """
        super().__init__(run_id)
        self._settings = settings or get_settings()
        self._ssh_target_factory = ssh_target_factory or (lambda: SSHTarget.from_vcs_settings(self._settings))
        self._ssh_connector_factory = ssh_connector_factory or _default_ssh_connector_factory

    async def run(self, test_case: TestCaseLike) -> TestRun:
        run_id = self.run_id
        params: dict[str, Any] = dict(getattr(test_case, "protocol_params", {}) or {})
        target = self._ssh_target_factory()
        connector = self._ssh_connector_factory(target)
        session: CollectorSession | None = None

        try:
            await job_runner.set_status(run_id, TestRunStatus.RUNNING, target_host=target.host)

            # 1. 설정 파일 업로드
            local_config_path = self._resolve_repo_path(test_case.config_ref)
            dest_path = params["dest_path"]
            await connector.upload_file(local_config_path, dest_path)
            logger.info("VolteExecutor(%s): uploaded %s -> %s", run_id, local_config_path, dest_path)

            # 2. vctp 재기동 (명령 자체는 TestCase.protocol_params에서 주입, 하드코딩 금지)
            restart_cmd = params["restart_cmd"]
            restart_result = await connector.run_command(restart_cmd)
            if not restart_result.ok:
                logger.warning(
                    "VolteExecutor(%s): restart_cmd exited non-zero (%s): stderr=%s",
                    run_id,
                    restart_result.exit_status,
                    restart_result.stderr,
                )

            wait_after = float(params.get("wait_after_restart_sec", 0) or 0)
            if wait_after > 0:
                await asyncio.sleep(wait_after)

            # 3. 로그 실시간 수집 시작
            log_paths = normalize_log_paths(params.get("vcs_log_paths") or {})
            if not log_paths:
                raise ValueError(
                    "protocol_params.vcs_log_paths가 비어있다 — 최소 vcsm_log/vcmm_log 경로가 필요하다"
                )
            sources = [
                CollectorSource(SshTailSource(name, path, target=target), channel="vcs_log")
                for name, path in log_paths.items()
            ]
            session = CollectorSession(
                run_id=run_id, test_case_id=test_case.id, sources=sources, settings=self._settings
            )
            await session.start()

            # 4. 완료(Pass) 또는 타임아웃까지 대기
            timeout_sec = float(params.get("timeout_sec", 30) or 30)
            pass_criteria = getattr(test_case, "pass_criteria", {}) or {}
            completion = await wait_for_completion(
                run_dir=session.run_dir,
                log_names=list(log_paths.keys()),
                run_id=run_id,
                pass_criteria=pass_criteria,
                timeout_sec=timeout_sec,
            )

            await session.stop()
            session = None  # 이미 정리됨

            # 5. 저장 + Call Flow 생성 + 최종 상태 반영
            await job_runner.set_status(
                run_id, TestRunStatus.PARSING, raw_log_path=str(self._run_dir_for(test_case.id, run_id))
            )
            await persist_results(run_id, completion.events, protocol="volte")

            final_status = TestRunStatus.DONE if completion.pass_fail.passed else TestRunStatus.FAILED
            summary = json.dumps(
                {
                    "passed": completion.pass_fail.passed,
                    "reasons": completion.pass_fail.reasons,
                    "timed_out": completion.timed_out,
                    "event_count": len(completion.events),
                }
            )
            await job_runner.set_status(run_id, final_status, result_summary=summary)
        finally:
            if session is not None:
                await session.stop()
            await connector.close()

        return await asyncio.to_thread(self._fetch_run, run_id)

    def _resolve_repo_path(self, config_ref: str) -> Path:
        p = Path(config_ref)
        if p.is_absolute():
            return p
        return self._settings.repo_root_path / config_ref

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
