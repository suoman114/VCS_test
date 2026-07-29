"""McpttBasicCallExecutor 통합 테스트 (CLAUDE.md §3.2).

실제 SIPp 바이너리는 절대 실행하지 않는다: 생성자에 이미 열려있는
`sipp_runner` 주입 지점에 즉시 성공 응답을 반환하는 가짜 러너를 넣는다.
VCS측 로그(`vcmc.log`, `vcmm.log`) 수집은 volte 테스트와 동일하게
`SshTailSource`를 로컬 샘플 파일 기반 스텁으로 대체해 실 SSH를 우회한다.
"""
from __future__ import annotations

import json
import shlex
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

import app.services.mcptt.executor as mcptt_executor_module
from app.core.config import Settings
from app.models.test_case import TestCase, TestCaseCategory, TestCaseType
from app.models.test_run import TestRun, TestRunStatus
from app.services.log_collector.base import LogSource
from app.services.log_collector.local_source import LocalFileSource
from app.services.mcptt.executor import McpttBasicCallExecutor, SippRunResult
from app.services.ssh_connector.client import CommandResult, SSHTarget

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MCPTT_VCMC_LOG = _REPO_ROOT / "docs" / "log_samples" / "mcptt" / "vcmc.log"
_MCPTT_VCMM_LOG = _REPO_ROOT / "docs" / "log_samples" / "mcptt" / "vcmm.log"


class _LocalTailStub(LogSource):
    """`SshTailSource`를 대체하는 스텁 (test_volte_executor.py와 동일한 패턴)."""

    def __init__(
        self,
        name: str,
        remote_path: str,
        *,
        target: SSHTarget | None = None,
        from_beginning: bool = False,
        retry_policy: object | None = None,
    ) -> None:
        self.name = name
        self._inner = LocalFileSource(name, remote_path, from_beginning=True, poll_interval=0.02)

    def stream(self, stop_event) -> AsyncIterator[str]:  # type: ignore[override]
        return self._inner.stream(stop_event)


@pytest.fixture(autouse=True)
def _local_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcptt_executor_module, "SshTailSource", _LocalTailStub)


def _seed_test_case_and_run(isolated_db) -> tuple[TestCase, str]:
    db = isolated_db()
    try:
        test_case = TestCase(
            name="mcptt-executor-qa-fixture",
            category=TestCaseCategory.MCPTT,
            test_type=TestCaseType.BASIC_CALL,
            config_ref="scenarios/sipp/mcptt_basic_call.xml",
            protocol_params={
                "target_ip": "10.0.0.10",
                "target_port": 5060,
                "max_calls": 10,
                "call_rate": 1,
                "vcs_log_paths": {
                    "vcmc_log": str(_MCPTT_VCMC_LOG),
                    "vcmm_log": str(_MCPTT_VCMM_LOG),
                },
                "timeout_sec": 5,
            },
            pass_criteria={},
        )
        db.add(test_case)
        db.commit()
        db.refresh(test_case)
        # 커밋은 세션 내 모든 객체의 속성을 만료(expire)시킨다. test_run 커밋 전에
        # test_case를 분리해야 executor.run()이 detached 상태에서도 이미 로드된
        # 속성 값을 그대로 쓸 수 있다 (test_volte_executor.py와 동일한 이유).
        db.expunge(test_case)

        test_run = TestRun(test_case_id=test_case.id, status=TestRunStatus.PENDING)
        db.add(test_run)
        db.commit()
        run_id = test_run.id
        db.expunge(test_run)
        return test_case, run_id
    finally:
        db.close()


@pytest.mark.asyncio
async def test_mcptt_executor_run_passes_with_sample_logs(isolated_db, tmp_path: Path) -> None:
    test_case, run_id = _seed_test_case_and_run(isolated_db)

    called_argv: list[list[str]] = []

    async def _fake_sipp_runner(argv: list[str], cwd: Path, timeout_sec: float) -> SippRunResult:
        called_argv.append(argv)
        return SippRunResult(argv=argv, exit_status=0, stdout="sipp ok", stderr="")

    executor = McpttBasicCallExecutor(
        run_id=run_id,
        # storage_dir을 tmp_path로 격리해 repo의 실제 storage/logs/를 오염시키지 않는다.
        settings=Settings(storage_dir=str(tmp_path / "storage")),
        ssh_target_factory=lambda: SSHTarget(host="fake-vcs"),
        sipp_runner=_fake_sipp_runner,
    )

    result_run = await executor.run(test_case)

    assert result_run.status == TestRunStatus.DONE
    assert result_run.result_summary is not None
    summary = json.loads(result_run.result_summary)
    assert summary["passed"] is True, summary["reasons"]
    assert summary["event_count"] > 0
    assert summary["sipp_exit_status"] == 0

    # SIPp가 실제로 (가짜) 실행됐고, 시나리오/파라미터가 CLAUDE.md §3.2 1단계대로 반영됐는지.
    assert len(called_argv) == 1
    argv = called_argv[0]
    assert argv[0] == "sipp"
    assert argv[1] == "10.0.0.10:5060"
    assert str(_REPO_ROOT / "scenarios" / "sipp" / "mcptt_basic_call.xml") in argv


@pytest.mark.asyncio
async def test_mcptt_executor_sipp_failure_still_evaluates_logs(isolated_db, tmp_path: Path) -> None:
    """SIPp 프로세스가 비정상 종료해도(exit != 0) 로그 기반 판정은 계속 수행된다.

    executor는 sipp 실패를 warning 로그로만 남기고 실행을 중단하지 않는다
    (app/services/mcptt/executor.py의 `if not sipp_result.ok: logger.warning(...)`).
    """
    test_case, run_id = _seed_test_case_and_run(isolated_db)

    async def _failing_sipp_runner(argv: list[str], cwd: Path, timeout_sec: float) -> SippRunResult:
        return SippRunResult(argv=argv, exit_status=1, stdout="", stderr="boom")

    executor = McpttBasicCallExecutor(
        run_id=run_id,
        settings=Settings(storage_dir=str(tmp_path / "storage")),
        ssh_target_factory=lambda: SSHTarget(host="fake-vcs"),
        sipp_runner=_failing_sipp_runner,
    )

    result_run = await executor.run(test_case)

    # VCS측 로그(샘플)는 여전히 성공을 나타내므로 최종 판정은 recording_stop_res 기준을 따른다.
    assert result_run.status == TestRunStatus.DONE
    summary = json.loads(result_run.result_summary)
    assert summary["sipp_exit_status"] == 1
    assert summary["passed"] is True


class _FakeSippSshConnector:
    """SIPp 전용 원격 호스트용 가짜 SSH 커넥터 (run_command/upload/download/close)."""

    def __init__(self, target: SSHTarget) -> None:
        self.target = target
        self.commands: list[str] = []
        self.uploaded: list[tuple[str, str]] = []
        self.downloaded: list[tuple[str, str]] = []
        self.closed = False

    async def run_command(self, command: str, timeout: float | None = None) -> CommandResult:
        self.commands.append(command)
        return CommandResult(command=command, exit_status=0, stdout="sipp ok", stderr="")

    async def upload_file(self, local_path: str | Path, remote_path: str) -> None:
        self.uploaded.append((str(local_path), remote_path))

    async def download_file(self, remote_path: str, local_path: str | Path) -> None:
        self.downloaded.append((remote_path, str(local_path)))
        Path(local_path).write_text("fake sipp log content")

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_mcptt_executor_remote_sipp_exec_mode_uploads_and_runs_remotely(
    isolated_db, tmp_path: Path
) -> None:
    """`sipp_exec_mode=ssh`일 때 시나리오 업로드 -> 원격 실행 -> 로그 다운로드가 일어나는지.

    실제 SIPp 전용 호스트 SSH 연결은 하지 않는다 — `sipp_ssh_connector_factory`
    주입 지점에 가짜 커넥터를 넣는다(VCS측 `ssh_target_factory`/`SshTailSource`는
    다른 테스트와 동일하게 로컬 샘플 로그로 대체된 상태).
    """
    test_case, run_id = _seed_test_case_and_run(isolated_db)
    test_case.protocol_params = {**test_case.protocol_params, "sipp_exec_mode": "ssh"}

    fake_sipp_connector = _FakeSippSshConnector(SSHTarget(host="fake-sipp"))

    executor = McpttBasicCallExecutor(
        run_id=run_id,
        settings=Settings(storage_dir=str(tmp_path / "storage")),
        ssh_target_factory=lambda: SSHTarget(host="fake-vcs"),
        sipp_ssh_target_factory=lambda: SSHTarget(host="fake-sipp"),
        sipp_ssh_connector_factory=lambda target: fake_sipp_connector,
    )

    result_run = await executor.run(test_case)

    assert result_run.status == TestRunStatus.DONE
    summary = json.loads(result_run.result_summary)
    assert summary["sipp_exit_status"] == 0
    assert summary["passed"] is True

    # 1. 원격 작업 디렉토리 생성
    assert any(cmd.startswith("mkdir -p") for cmd in fake_sipp_connector.commands)

    # 2. 시나리오가 로컬 저장소 경로 -> 원격 경로로 업로드됐는지
    assert len(fake_sipp_connector.uploaded) == 1
    local_scenario, remote_scenario = fake_sipp_connector.uploaded[0]
    assert local_scenario == str(_REPO_ROOT / "scenarios" / "sipp" / "mcptt_basic_call.xml")
    assert remote_scenario.endswith("/mcptt_basic_call.xml")
    assert test_case.id in remote_scenario
    assert run_id in remote_scenario

    # 3. sipp 커맨드가 원격 경로 기준으로 구성되어 실행됐는지
    sipp_cmd = fake_sipp_connector.commands[-1]
    assert sipp_cmd.startswith("sipp ")
    assert remote_scenario in sipp_cmd or shlex.quote(remote_scenario) in sipp_cmd

    # 4. SIPp 자체 로그 3종이 로컬로 다운로드됐는지 (원본 로그 보존)
    assert len(fake_sipp_connector.downloaded) == 3
    downloaded_names = {remote.rsplit("/", 1)[-1] for remote, _ in fake_sipp_connector.downloaded}
    assert downloaded_names == {"sipp_messages.log", "sipp_screen.log", "sipp_stats.csv"}

    assert fake_sipp_connector.closed is True
