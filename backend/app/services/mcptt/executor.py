"""McPTT 기본 호처리 시험 실행기 (CLAUDE.md §3.2).

절차:
    1. `TestCase.config_ref`(SIPp 시나리오 XML, 저장소 루트 기준 상대 경로)와
       `protocol_params`로 SIPp 커맨드라인을 구성한다
       (`scenarios/sipp/README.md`의 파라미터 매핑표 기준).
    2. VCS측 로그(`vcmc.log`, `vcmm.log`) `CollectorSession` tail 수집을 먼저
       시작한 뒤, SIPp 프로세스를 실행한다(동시 수집, CLAUDE.md §3.2 2~3단계).
    3. SIPp 실행이 끝나면(또는 동시에) `pass_criteria` 충족/타임아웃까지
       수집된 로그를 재파싱하며 대기한다.
    4. 수집 종료 -> CallEvent 저장 -> Call Flow 생성 -> 최종 상태 반영.

SIPp 실행 위치(`sipp_exec_mode`)는 CLAUDE.md §13 TBD다. `local`(기본값,
`Settings.sipp_exec_mode` 또는 `protocol_params["sipp_exec_mode"]`)은
자동화 서버에서 `asyncio.create_subprocess_exec`로 바로 실행한다. `ssh`는
인터페이스만 열어두고 TODO로 남긴다(`_run_sipp_remote`).

`TestCase.protocol_params` 키(요구 사항, 완료 보고 참고 — `scenarios/sipp/README.md`
제안표와 실제 `testcases/mcptt/mcptt_basic_call_001.yaml` 예시 사이의 이름 불일치를
양쪽 다 허용하도록 fallback을 둔다):
    target_host | target_ip (str, 필수) : VCS(vcmc) 대상 IP
    target_port (int, 기본 5060)        : VCS SIP 포트
    local_ip (str, 선택)                 : SIPp 바인딩 로컬 IP (-i)
    local_port (int, 선택)               : SIPp 로컬 SIP 포트 (-p)
    transport (str, 기본 "u1")           : SIP 전송 프로토콜
    callee_id (str, 선택)                : 착신 MCPTT 번호 (-s)
    caller_id (str, 선택)                : 발신 MCPTT 사용자 ID (-key mcptt_caller_id)
    group_id (str, 선택)                 : MCPTT 그룹 ID (-key mcptt_group_id)
    mcptt_domain (str, 선택)             : 발신자 PLMN 도메인 (-key mcptt_domain)
    calls_count | max_calls (int, 기본 1): 총 호 발생 수 (-m)
    call_rate (float, 기본 1)            : 초당 호 발생율 (-r)
    extra_sipp_args (list[str], 선택)    : 추가 SIPp 인자 그대로 append
    vcs_log_paths (list[str] | dict, 필수): VCS측 tail 대상 로그 경로들
                                            (예: vcmc.log, vcmm.log)
    sipp_exec_mode ("local"|"ssh", 선택) : 기본값은 Settings.sipp_exec_mode
    timeout_sec (float, 기본 30)         : 완료 판정 타임아웃
    sipp_bin (str, 기본 "sipp")          : SIPp 실행 파일 경로/이름
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.job_runner import job_runner
from app.models.test_run import TestRun, TestRunStatus
from app.services.execution_common import normalize_log_paths, persist_results, wait_for_completion
from app.services.executor_base import TestCaseLike, TestExecutor, executor_registry
from app.services.log_collector import CollectorSession, CollectorSource, SshTailSource
from app.services.ssh_connector import SSHTarget

logger = logging.getLogger(__name__)


@dataclass
class SippRunResult:
    argv: list[str]
    exit_status: int | None
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


SippRunner = Callable[[list[str], Path, float], Awaitable[SippRunResult]]


async def _default_local_sipp_runner(argv: list[str], cwd: Path, timeout_sec: float) -> SippRunResult:
    """`asyncio.create_subprocess_exec`로 로컬에서 SIPp를 실행하는 기본 구현체.

    QA/Integration Agent는 이 함수 대신 가짜(mocked) `SippRunner`를 executor
    생성자에 주입해 실제 SIPp 바이너리 없이 테스트할 수 있다.
    """
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return SippRunResult(argv=argv, exit_status=None, stdout="", stderr="sipp process timed out")
    return SippRunResult(
        argv=argv,
        exit_status=process.returncode,
        stdout=stdout.decode(errors="replace") if stdout else "",
        stderr=stderr.decode(errors="replace") if stderr else "",
    )


def build_sipp_args(
    scenario_path: Path,
    params: dict[str, Any],
    run_dir: Path,
    *,
    sipp_bin: str = "sipp",
) -> list[str]:
    """`TestCase.protocol_params` -> SIPp 커맨드라인 인자 목록.

    `scenarios/sipp/README.md`가 제안한 키(`target_host`, `calls_count`)와
    `testcases/mcptt/mcptt_basic_call_001.yaml` 예시가 실제로 쓰는 키
    (`target_ip`, `max_calls`)가 서로 달라, 이 함수는 두 이름을 모두
    허용한다(완료 보고에 불일치 명시, testcase-manager-agent와 조율 필요).
    """
    target_host = params.get("target_host") or params.get("target_ip")
    if not target_host:
        raise ValueError("protocol_params에 target_host(또는 target_ip)가 필요하다")
    target_port = params.get("target_port", 5060)
    calls_count = params.get("calls_count") or params.get("max_calls", 1)
    call_rate = params.get("call_rate", 1)

    argv: list[str] = [
        sipp_bin,
        f"{target_host}:{target_port}",
        "-sf",
        str(scenario_path),
        "-m",
        str(calls_count),
        "-r",
        str(call_rate),
    ]

    local_ip = params.get("local_ip")
    if local_ip:
        argv += ["-i", str(local_ip)]
    local_port = params.get("local_port")
    if local_port:
        argv += ["-p", str(local_port)]
    transport = params.get("transport", "u1")
    if transport:
        argv += ["-t", str(transport)]
    callee_id = params.get("callee_id")
    if callee_id:
        argv += ["-s", str(callee_id)]
    caller_id = params.get("caller_id")
    if caller_id:
        argv += ["-key", "mcptt_caller_id", str(caller_id)]
    group_id = params.get("group_id")
    if group_id:
        argv += ["-key", "mcptt_group_id", str(group_id)]
    mcptt_domain = params.get("mcptt_domain")
    if mcptt_domain:
        argv += ["-key", "mcptt_domain", str(mcptt_domain)]

    argv += [
        "-trace_msg",
        "-message_file",
        str(run_dir / "sipp_messages.log"),
        "-trace_screen",
        "-screen_file",
        str(run_dir / "sipp_screen.log"),
        "-trace_stat",
        "-stf",
        str(run_dir / "sipp_stats.csv"),
    ]

    extra_args = params.get("extra_sipp_args") or []
    argv += [str(a) for a in extra_args]
    return argv


@executor_registry.register(protocol="mcptt", test_type="basic_call")
class McpttBasicCallExecutor(TestExecutor):
    """CLAUDE.md §3.2 McPTT 기본 호처리 시험 실행기."""

    protocol = "mcptt"
    test_type = "basic_call"

    def __init__(
        self,
        run_id: str,
        *,
        settings: Settings | None = None,
        sipp_runner: SippRunner | None = None,
        ssh_target_factory: Callable[[], SSHTarget] | None = None,
    ) -> None:
        """`sipp_runner`는 QA/Integration Agent가 실제 SIPp 바이너리 없이
        모킹할 수 있도록 열어둔 의존성 주입 지점이다.
        """
        super().__init__(run_id)
        self._settings = settings or get_settings()
        self._sipp_runner = sipp_runner or _default_local_sipp_runner
        self._ssh_target_factory = ssh_target_factory or (lambda: SSHTarget.from_vcs_settings(self._settings))

    async def run(self, test_case: TestCaseLike) -> TestRun:
        run_id = self.run_id
        params: dict[str, Any] = dict(getattr(test_case, "protocol_params", {}) or {})
        target = self._ssh_target_factory()
        session: CollectorSession | None = None

        try:
            await job_runner.set_status(run_id, TestRunStatus.RUNNING, target_host=target.host)

            # VCS측 로그 tail을 SIPp 실행 전에 먼저 시작한다 (CLAUDE.md §3.2 2~3단계).
            log_paths = normalize_log_paths(params.get("vcs_log_paths") or {})
            if not log_paths:
                raise ValueError(
                    "protocol_params.vcs_log_paths가 비어있다 — 최소 vcmc_log/vcmm_log 경로가 필요하다"
                )
            sources = [
                CollectorSource(SshTailSource(name, path, target=target), channel="vcs_log")
                for name, path in log_paths.items()
            ]
            session = CollectorSession(run_id=run_id, test_case_id=test_case.id, sources=sources)
            await session.start()

            scenario_path = self._resolve_repo_path(test_case.config_ref)
            timeout_sec = float(params.get("timeout_sec", 30) or 30)
            argv = build_sipp_args(
                scenario_path, params, session.run_dir, sipp_bin=params.get("sipp_bin", "sipp")
            )

            exec_mode = params.get("sipp_exec_mode", self._settings.sipp_exec_mode)
            sipp_result = await self._run_sipp(argv, exec_mode, timeout_sec)
            if not sipp_result.ok:
                logger.warning(
                    "McpttExecutor(%s): sipp exited non-zero (%s): stderr=%s",
                    run_id,
                    sipp_result.exit_status,
                    sipp_result.stderr,
                )

            pass_criteria = getattr(test_case, "pass_criteria", {}) or {}
            completion = await wait_for_completion(
                run_dir=session.run_dir,
                log_names=list(log_paths.keys()),
                run_id=run_id,
                pass_criteria=pass_criteria,
                timeout_sec=timeout_sec,
            )

            await session.stop()
            session = None

            await job_runner.set_status(
                run_id, TestRunStatus.PARSING, raw_log_path=str(self._run_dir_for(test_case.id, run_id))
            )
            await persist_results(run_id, completion.events, protocol="mcptt")

            final_status = TestRunStatus.DONE if completion.pass_fail.passed else TestRunStatus.FAILED
            summary = json.dumps(
                {
                    "passed": completion.pass_fail.passed,
                    "reasons": completion.pass_fail.reasons,
                    "timed_out": completion.timed_out,
                    "event_count": len(completion.events),
                    "sipp_exit_status": sipp_result.exit_status,
                }
            )
            await job_runner.set_status(run_id, final_status, result_summary=summary)
        finally:
            if session is not None:
                await session.stop()

        return await asyncio.to_thread(self._fetch_run, run_id)

    async def _run_sipp(self, argv: list[str], exec_mode: str, timeout_sec: float) -> SippRunResult:
        if exec_mode == "local":
            return await self._sipp_runner(argv, self._settings.repo_root_path, timeout_sec)
        if exec_mode == "ssh":
            # TODO(CLAUDE.md §13 TBD): SIPp 원격(전용 호스트) 실행. 시나리오/파라미터
            # 정의는 실행 위치와 무관하게 재사용 가능하다고 문서화되어 있으므로
            # (scenarios/sipp/README.md), SSHTarget.from_sipp_settings()로 연결해
            # 동일 argv를 원격 커맨드라인으로 감싸 실행하면 된다. 실제 배포 환경
            # 확인 전까지는 명시적으로 미구현 상태로 남긴다.
            raise NotImplementedError(
                "sipp_exec_mode='ssh' (원격 SIPp 실행)은 아직 구현하지 않았다 (CLAUDE.md §13 TBD)"
            )
        raise ValueError(f"unknown sipp_exec_mode: {exec_mode!r}")

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
