"""VoLTE 기본 호처리 시험 실행기 (CLAUDE.md §3.1).

절차 (2026-07-29 실제 VCS 환경 확인 후 확정):
    1. vctp가 재생(replay)할 pcap 샘플 파일은 이미 VCS의
       `Settings.vctp_sample_dir`(기본 `/home/vcs/vctp/sample`)에 있다. 새로
       업로드하지 않고, `protocol_params["sample_file"]`로 지정된 파일명을
       vctp 설정(`Settings.vctp_config_path`)의 `SAMPLEFILE1` 항목에 반영한다
       (`_apply_sample_file`, SSH로 `sed` 실행).
    2. SSH로 vctp를 정지 후 재시작한다: `protocol_params["stop_cmd"]`
       (기본 `Settings.vctp_stop_cmd`, `stopmc -b vctp`) ->
       `protocol_params["start_cmd"]`(기본 `Settings.vctp_start_cmd`,
       `startmc -b vctp`) 순서로 두 명령을 순차 실행.
    3. `vcsm.log`/`vcmm.log`(기본 경로는 `Settings.vcs_vcsm_log_path`/
       `vcs_vcmm_log_path`, `protocol_params`로 override 가능)를
       `CollectorSession`으로 실시간 tail 수집 시작.
    4. `pass_criteria` 충족 또는 `protocol_params["timeout_sec"]` 타임아웃까지
       주기적으로 재파싱하며 대기.
    5. 수집 종료 -> CallEvent 저장 -> Call Flow(Mermaid) 생성 -> 최종 상태
       (`done`/`failed`) 반영.

`TestCase.protocol_params` 키:
    sample_file (str, 필수)          : `Settings.vctp_sample_dir` 안의 pcap 파일명
                                       (전체 경로 아님, 파일명만). Test Case 등록
                                       폼에서는 `GET /api/vcs/volte-sample-files`로
                                       조회한 목록 중 하나를 select box로 고른다.
    vctp_config_path (str, 선택)     : 기본값 Settings.vctp_config_path
    stop_cmd / start_cmd (str, 선택) : 기본값 Settings.vctp_stop_cmd / vctp_start_cmd
    vcsm_log_path / vcmm_log_path    : 기본값 Settings.vcs_vcsm_log_path / vcs_vcmm_log_path /
        / vctp_log_path (str, 선택)     vcs_vctp_log_path. vctp_log는 패킷 릴레이 노이즈가 대부분
                                       (CLAUDE.md §9)이지만 대시보드 프로세스별 로그 탭 요구사항에
                                       따라 다른 로그와 동일하게 tail한다.
    vcs_log_paths (list[str] | dict) : 위 세 기본 경로 외에 추가로 tail할 로그가 있으면 병합한다.
        (선택)
    wait_after_restart_sec (float)   : 재기동 후 로그 수집 시작 전 대기(기본 0)
    timeout_sec (float)              : 완료 판정 타임아웃(기본 120초). `recording_stop_res`
                                       성공 이벤트가 확인되면 이 값을 다 기다리지 않고 즉시
                                       종료된다(`wait_for_completion`) — pcap마다 실제 통화
                                       길이가 다르므로 정확한 값을 몰라도, 가장 긴 pcap보다
                                       넉넉하게만 잡으면 된다. 너무 짧게 잡으면(예: 기존 기본값
                                       30초) 호가 끝나기 전에 타임아웃으로 실패 처리될 수 있다.

> `sed`로 `SAMPLEFILE1`을 치환하는 정확한 라인 문법은 `vctp.log`에 찍히는
> 파싱된 출력(`Config [SAMPLEFILE1 = imsVideo30sec.pcap]`)에서 역추정한
> 것이라, 실제 설정 파일의 공백/구분자가 다르면 정규식을 조정해야 할 수
> 있다(최초 실 서버 실행 시 검증 필요).
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
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

            # 1. vctp 설정의 SAMPLEFILE1을 선택된 pcap 파일로 교체
            sample_file = params.get("sample_file")
            if not sample_file:
                raise ValueError(
                    "protocol_params.sample_file이 비어있다 — /api/vcs/volte-sample-files에서"
                    " 조회한 파일명 중 하나를 지정해야 한다"
                )
            config_path = params.get("vctp_config_path", self._settings.vctp_config_path)
            await self._apply_sample_file(connector, config_path, sample_file)
            logger.info("VolteExecutor(%s): set SAMPLEFILE1=%s in %s", run_id, sample_file, config_path)

            # 2. vctp 재기동 (정지 -> 시작 순차 실행, 명령 자체는 protocol_params/Settings에서 주입)
            stop_cmd = params.get("stop_cmd", self._settings.vctp_stop_cmd)
            start_cmd = params.get("start_cmd", self._settings.vctp_start_cmd)
            for cmd in (stop_cmd, start_cmd):
                cmd_result = await connector.run_command(cmd)
                if not cmd_result.ok:
                    logger.warning(
                        "VolteExecutor(%s): command %r exited non-zero (%s): stderr=%s",
                        run_id,
                        cmd,
                        cmd_result.exit_status,
                        cmd_result.stderr,
                    )

            wait_after = float(params.get("wait_after_restart_sec", 0) or 0)
            if wait_after > 0:
                await asyncio.sleep(wait_after)

            # 3. 로그 실시간 수집 시작 (기본 경로는 Settings, protocol_params로 override/추가 가능)
            default_log_paths = {
                "vcsm_log": params.get("vcsm_log_path", self._settings.vcs_vcsm_log_path),
                "vcmm_log": params.get("vcmm_log_path", self._settings.vcs_vcmm_log_path),
                "vctp_log": params.get("vctp_log_path", self._settings.vcs_vctp_log_path),
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

            # 4. 완료(Pass) 또는 타임아웃까지 대기
            timeout_sec = float(params.get("timeout_sec", 120) or 120)
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

    @staticmethod
    async def _apply_sample_file(connector: SSHConnector, config_path: str, sample_file: str) -> None:
        """vctp 설정 파일의 `SAMPLEFILE1` 값을 `sample_file`로 치환한다.

        정확한 라인 문법은 vctp.log의 파싱된 출력에서 역추정한 것이라
        (모듈 docstring 참고), `=` 앞뒤 공백 유무를 유연하게 허용하는
        정규식으로 치환한다.
        """
        escaped = sample_file.replace("\\", r"\\").replace("/", r"\/").replace("&", r"\&")
        command = (
            "sed -i -E "
            f"'s/^(SAMPLEFILE1[[:space:]]*=[[:space:]]*).*/\\1{escaped}/' "
            f"{shlex.quote(config_path)}"
        )
        result = await connector.run_command(command)
        if not result.ok:
            raise RuntimeError(
                f"failed to set SAMPLEFILE1={sample_file!r} in {config_path}: "
                f"{result.stderr or result.stdout}"
            )

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
