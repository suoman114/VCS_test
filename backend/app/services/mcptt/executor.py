"""McPTT 기본 호처리 시험 실행기 (CLAUDE.md §3.2).

절차:
    1. `protocol_params.scenario_file`(SIPp 전용 호스트의 `Settings.mcptt_sim_dir`
       안에 이미 있는 시나리오 XML 파일명 — VoLTE의 pcap 샘플 선택과 동일한
       패턴, `GET /api/vcs/mcptt-scenario-files`로 select box 제공)과
       `protocol_params`로 실행 커맨드라인을 구성한다.
    2. VCS측 로그(`vcmc.log`, `vcmm.log`) `CollectorSession` tail 수집을 먼저
       시작한 뒤, 시뮬레이터를 실행한다(동시 수집, CLAUDE.md §3.2 2~3단계).
    3. 실행이 끝나면(또는 동시에) `pass_criteria` 충족/타임아웃까지 수집된
       로그를 재파싱하며 대기한다.
    4. 수집 종료 -> CallEvent 저장 -> Call Flow 생성 -> 최종 상태 반영.

실행 위치(`sipp_exec_mode`, `Settings.sipp_exec_mode` 또는
`protocol_params["sipp_exec_mode"]`로 결정, 기본값 `local`):
    - `local`: 자동화 서버에서 실제 SIPp 바이너리를 `asyncio.create_subprocess_exec`로
      직접 실행한다(개발/테스트용 경로 — 실 배포에서는 쓰이지 않는다,
      `build_sipp_args`).
    - `ssh`: 별도 SIPp 전용 호스트에 SSH로 접속해 실행한다(2026-07-29 확인:
      실 배포는 항상 이 모드). **실제 SIPp가 아니라, 그 호스트에 이미 올라가
      있는 자체 제작 Java 도구(`Settings.mcptt_sim_dir`/`mcptt_sim_jar_name`,
      기본 `/root/mcptt_sim/utgen-jar-with-dependencies.jar`)를 실행한다**
      (2026-07-29 확인, `build_mcptt_sim_args`). 시나리오 XML도 그 디렉토리에
      이미 있으므로 업로드가 필요 없고, 이 도구는 SIPp 트레이스 파일을
      만들지 않으므로 다운로드할 로그도 없다 — `vcmc.log`/`vcmm.log`만이
      이 시험의 로그 소스다(`_run_sipp_remote`).

`TestCase.protocol_params` 키:
    scenario_file (str, 필수)            : `Settings.mcptt_sim_dir` 안의 시나리오
                                            XML 파일명(전체 경로 아님). Test Case
                                            등록 폼은 `GET /api/vcs/mcptt-scenario-files`로
                                            조회한 목록 중 하나를 select box로 고른다.
                                            안 채우면 `TestCase.config_ref`로 폴백한다.
    target_host | target_ip (str, 선택) : VCS(vcmc) 대상 IP. ssh 모드에서는 안 채우면
                                            대시보드 "설정"에 저장된 VCS 접속 IP를 그대로
                                            쓴다(2026-07-30) — local 모드는 여전히 필수.
    target_port (int, 기본 Settings.mcptt_sim_target_port=5060)     : VCS SIP 포트
    local_ip (str, 기본 Settings.mcptt_sim_local_ip)                : 시뮬레이터 바인딩 로컬 IP (-i)
    local_port (int, 기본 Settings.mcptt_sim_local_port=5080)       : 시뮬레이터 로컬 포트 (-p)
    control_port (int, 기본 Settings.mcptt_sim_control_port=6061)   : 시뮬레이터 컨트롤 포트 (-cp)
    calls_count | max_calls (int, 기본 1): 총 호 발생 수 (-m)
    extra_sipp_args (list[str], 선택)    : 추가 인자 그대로 append
    vcmc_log_path / vcmm_log_path        : 기본값 Settings.vcs_vcmc_log_path / vcs_vcmm_log_path
        (str, 선택)
    vcs_log_paths (list[str] | dict, 선택): 위 두 기본 경로 외에 추가로 tail할 로그
    sipp_exec_mode ("local"|"ssh", 선택) : 기본값은 Settings.sipp_exec_mode
    mcptt_sim_dir / mcptt_sim_jar_name   : 기본값 Settings.mcptt_sim_dir / mcptt_sim_jar_name
        (str, 선택)
    timeout_sec (float, 기본 120)        : 완료 판정 타임아웃(상한). `recording_stop_res`
                                            성공 이벤트가 확인되면 이 값을 다 기다리지 않고
                                            즉시 종료된다(`wait_for_completion`) — 시나리오마다
                                            실제 호 길이가 다르므로 정확한 값을 몰라도, 가장
                                            오래 걸리는 시나리오보다 넉넉하게만 잡으면 된다.

SIPp 전용 호스트가 root 직접 SSH 로그인을 막아놔서(`PermitRootLogin no`)
`sipp_ssh_username`(예: sysadm)으로 접속한 뒤 `su - root`로 전환해야 하는
환경 대응(2026-07-29): `Settings.sipp_ssh_root_password`(또는 대시보드
"설정"의 SIPp root 비밀번호)가 채워져 있으면, 시뮬레이터 실행 자체를
`SSHConnector.run_command_as_su()`로 root 권한으로 돌린다 — 비어있으면
`sipp_ssh_username` 권한으로 직접 실행한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.job_runner import job_runner
from app.models.test_run import TestRun, TestRunStatus
from app.services.execution_common import normalize_log_paths, persist_results, wait_for_completion
from app.services.executor_base import TestCaseLike, TestExecutor, executor_registry
from app.services.log_collector import CollectorSession, CollectorSource, SshTailSource
from app.services.ssh_connector import SSHConnector, SSHTarget
from app.services.vcs_settings_store import (
    resolve_sipp_exec_mode,
    resolve_sipp_root_password,
    resolve_sipp_target,
    resolve_vcs_target,
)

logger = logging.getLogger(__name__)


def _default_ssh_connector_factory(target: SSHTarget) -> SSHConnector:
    return SSHConnector(target)


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


def build_mcptt_sim_args(
    scenario_path: PurePosixPath,
    params: dict[str, Any],
    *,
    jar_path: str,
) -> list[str]:
    """`TestCase.protocol_params` -> McPTT 시뮬레이터(Java 도구) 커맨드라인.

    SIPp 전용 호스트에 이미 올라가 있는 자체 제작 Java 도구
    (`utgen-jar-with-dependencies.jar`)를 실행한다 — 실제 SIPp 바이너리가
    아니다(2026-07-29 확인). 예:
        java -jar utgen-jar-with-dependencies.jar -sf scenario.xml
             -i 192.168.7.65 -p 5080 -cp 6061 -m 1 10.0.0.1:5060
    """
    target_host = params.get("target_host") or params.get("target_ip")
    if not target_host:
        raise ValueError("protocol_params에 target_host(또는 target_ip)가 필요하다")
    target_port = params.get("target_port", 5060)
    calls_count = params.get("calls_count") or params.get("max_calls", 1)

    argv: list[str] = ["java", "-jar", jar_path, "-sf", str(scenario_path)]

    local_ip = params.get("local_ip")
    if local_ip:
        argv += ["-i", str(local_ip)]
    local_port = params.get("local_port")
    if local_port:
        argv += ["-p", str(local_port)]
    control_port = params.get("control_port")
    if control_port:
        argv += ["-cp", str(control_port)]

    argv += ["-m", str(calls_count), f"{target_host}:{target_port}"]

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
        sipp_ssh_target_factory: Callable[[], SSHTarget] | None = None,
        sipp_ssh_connector_factory: Callable[[SSHTarget], SSHConnector] | None = None,
    ) -> None:
        """`sipp_runner`(로컬 실행용)와 `sipp_ssh_connector_factory`(원격 실행용)는
        QA/Integration Agent가 실제 SIPp 바이너리/SSH 연결 없이 모킹할 수 있도록
        열어둔 의존성 주입 지점이다.
        """
        super().__init__(run_id)
        self._settings = settings or get_settings()
        self._sipp_runner = sipp_runner or _default_local_sipp_runner
        self._ssh_target_factory = ssh_target_factory or (lambda: resolve_vcs_target(self._settings))
        self._sipp_ssh_target_factory = sipp_ssh_target_factory or (
            lambda: resolve_sipp_target(self._settings)
        )
        self._sipp_ssh_connector_factory = sipp_ssh_connector_factory or _default_ssh_connector_factory

    async def run(self, test_case: TestCaseLike) -> TestRun:
        run_id = self.run_id
        params: dict[str, Any] = dict(getattr(test_case, "protocol_params", {}) or {})
        target = self._ssh_target_factory()
        session: CollectorSession | None = None

        try:
            await job_runner.set_status(run_id, TestRunStatus.RUNNING, target_host=target.host)

            # VCS측 로그 tail을 SIPp 실행 전에 먼저 시작한다 (CLAUDE.md §3.2 2~3단계).
            # 기본 경로는 Settings, protocol_params로 override/추가 가능.
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

            timeout_sec = float(params.get("timeout_sec", 120) or 120)
            exec_mode = params.get("sipp_exec_mode", resolve_sipp_exec_mode(self._settings))

            if exec_mode == "ssh":
                scenario_file = params.get("scenario_file") or test_case.config_ref
                if not scenario_file:
                    raise ValueError(
                        "protocol_params.scenario_file(또는 config_ref)이 필요하다 —"
                        " GET /api/vcs/mcptt-scenario-files에서 조회한 파일명 중 하나를 지정해야 한다"
                    )
                sim_dir = params.get("mcptt_sim_dir", self._settings.mcptt_sim_dir)
                jar_name = params.get("mcptt_sim_jar_name", self._settings.mcptt_sim_jar_name)
                remote_scenario_path = PurePosixPath(sim_dir) / scenario_file
                jar_path = PurePosixPath(sim_dir) / jar_name
                # target_host는 대시보드 "설정"에 저장된 VCS 접속 IP(위에서 이미
                # 구한 target.host)를 그대로 쓰고, 나머지 실행 파라미터는 Settings
                # 고정값을 기본으로 깐다 — protocol_params에 명시적으로 넣으면
                # (기존 target_ip 키 포함) 그 값이 항상 우선한다(2026-07-30 요청:
                # 매번 JSON에 직접 채우지 않아도 되게). setdefault를 써서, 이미
                # target_ip만 넣은 기존 Test Case도 그대로 존중한다 — 무조건
                # target_host를 덮어쓰면 target_ip가 있어도 항상 VCS 설정값이
                # 이겨버린다(build_mcptt_sim_args의 `target_host or target_ip`
                # 우선순위 때문).
                sim_params: dict[str, Any] = dict(params)
                sim_params.setdefault("target_host", sim_params.get("target_ip") or target.host)
                sim_params.setdefault("target_port", self._settings.mcptt_sim_target_port)
                sim_params.setdefault("local_ip", self._settings.mcptt_sim_local_ip)
                sim_params.setdefault("local_port", self._settings.mcptt_sim_local_port)
                sim_params.setdefault("control_port", self._settings.mcptt_sim_control_port)
                argv = build_mcptt_sim_args(remote_scenario_path, sim_params, jar_path=str(jar_path))
                sipp_result = await self._run_sipp_remote(argv=argv, timeout_sec=timeout_sec)
            elif exec_mode == "local":
                scenario_local_path = self._resolve_repo_path(test_case.config_ref)
                sipp_bin = params.get("sipp_bin", "sipp")
                argv = build_sipp_args(scenario_local_path, params, session.run_dir, sipp_bin=sipp_bin)
                sipp_result = await self._sipp_runner(argv, self._settings.repo_root_path, timeout_sec)
            else:
                raise ValueError(f"unknown sipp_exec_mode: {exec_mode!r}")

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

    async def _run_sipp_remote(self, *, argv: list[str], timeout_sec: float) -> SippRunResult:
        """SIPp 전용 원격 호스트에서 McPTT 시뮬레이터(Java 도구)를 실행한다.

        시나리오 XML은 이미 원격 `mcptt_sim_dir`에 있으므로(select box로
        고르기만 함, 모듈 docstring 참고) 업로드가 필요 없고, 이 도구는 SIPp
        트레이스 파일을 만들지 않으므로 다운로드할 로그도 없다(2026-07-29
        확정) — `vcmc.log`/`vcmm.log`만이 이 시험의 로그 소스다. 그래서 원격
        작업 디렉토리 생성/권한 조정도 필요 없이, 커맨드 하나만 실행한다.

        root 직접 SSH 로그인이 막힌 환경(2026-07-29, `resolve_sipp_root_password`)
        에서는 이 명령 자체를 `run_command_as_su()`로 root 권한으로 돌린다 —
        비어있으면 로그인 계정(sysadm) 권한으로 직접 실행한다.
        """
        target = self._sipp_ssh_target_factory()
        connector = self._sipp_ssh_connector_factory(target)
        root_password = resolve_sipp_root_password(self._settings)
        command = " ".join(shlex.quote(a) for a in argv)
        try:
            if root_password:
                result = await connector.run_command_as_su(command, root_password, timeout=timeout_sec)
            else:
                result = await connector.run_command(command, timeout=timeout_sec)
        except TimeoutError:
            return SippRunResult(argv=argv, exit_status=None, stdout="", stderr="sipp process timed out (remote)")
        finally:
            await connector.close()
        return SippRunResult(argv=argv, exit_status=result.exit_status, stdout=result.stdout, stderr=result.stderr)

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
