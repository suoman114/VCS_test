"""McpttPerformanceExecutor 통합 테스트 (2026-07-30 추가, CLAUDE.md §7).

실제 SSH/원격 프로세스는 절대 건드리지 않는다: `sipp_ssh_connector_factory`
주입 지점에 가짜 커넥터를 넣는다. VCS측 로그(vcmc.log, vcmm.log) 수집은
기존 McpttBasicCallExecutor 테스트와 동일하게 `SshTailSource`를 로컬 샘플
파일 기반 스텁으로 대체해 실 SSH를 우회한다.

가장 중요하게 검증하는 것: "종료" 버튼(= job_runner.cancel() -> asyncio
Task.cancel())을 눌렀을 때 (a) 원격 프로세스가 실제로 종료되고(커넥터의
run_command_cancellable이 CancelledError를 받는지), (b) TestRun이 ERROR가
아니라 DONE으로 정상 마무리되는지(성능 시험에서 수동 종료는 실패가 아니다).
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

import app.services.mcptt.performance_executor as mcptt_perf_executor_module
from app.core.config import Settings
from app.models.test_case import TestCase, TestCaseCategory, TestCaseType
from app.models.test_run import TestRun, TestRunStatus
from app.services.log_collector.base import LogSource
from app.services.log_collector.local_source import LocalFileSource
from app.services.mcptt.performance_executor import McpttPerformanceExecutor
from app.services.ssh_connector.client import CommandResult, SSHTarget

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MCPTT_VCMC_LOG = _REPO_ROOT / "docs" / "log_samples" / "mcptt" / "vcmc.log"
_MCPTT_VCMM_LOG = _REPO_ROOT / "docs" / "log_samples" / "mcptt" / "vcmm.log"


class _LocalTailStub(LogSource):
    """`SshTailSource`를 대체하는 스텁 (test_mcptt_executor.py와 동일한 패턴)."""

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
    monkeypatch.setattr(mcptt_perf_executor_module, "SshTailSource", _LocalTailStub)


class _FakePerfSippConnector:
    """성능 시뮬레이터 실행용 가짜 SSH 커넥터. `hang=True`면
    `run_command_cancellable`이 취소될 때까지 반환하지 않는다 — 무기한
    실행되는 실제 성능 시험 명령을 흉내낸다."""

    def __init__(self, *, hang: bool = False) -> None:
        self.commands: list[str] = []
        self.closed = False
        self._hang = hang
        self.cancelled = False

    async def run_command_cancellable(self, command: str, *, timeout: float | None = None) -> CommandResult:
        self.commands.append(command)
        if self._hang:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        else:
            # 로컬 샘플 로그를 tail하는 백그라운드 태스크(0.02초 주기)가 최소
            # 몇 사이클은 돌아 파일을 실제로 읽어들일 시간을 준다 — 즉시
            # 반환하면 폴링 루프가 첫 파싱 전에 stop_poll을 받아 이벤트가
            # 0건으로 보일 수 있다(실제 원격 명령은 이렇게 순식간에 안 끝남).
            await asyncio.sleep(0.3)
        return CommandResult(command=command, exit_status=0, stdout="ok", stderr="")

    async def close(self) -> None:
        self.closed = True


def _seed_test_case_and_run(isolated_db, *, protocol_params: dict[str, object]) -> tuple[TestCase, str]:
    db = isolated_db()
    try:
        test_case = TestCase(
            name="mcptt-performance-qa-fixture",
            category=TestCaseCategory.MCPTT,
            test_type=TestCaseType.PERFORMANCE,
            config_ref="mcptt_basic_call.xml",
            protocol_params={
                "sipp_exec_mode": "ssh",
                "scenario_file": "mcptt_basic_call.xml",
                "target_ip": "10.0.0.10",
                "vcs_log_paths": {
                    "vcmc_log": str(_MCPTT_VCMC_LOG),
                    "vcmm_log": str(_MCPTT_VCMM_LOG),
                },
                **protocol_params,
            },
            pass_criteria={},
        )
        db.add(test_case)
        db.commit()
        db.refresh(test_case)
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
async def test_missing_call_rate_raises(isolated_db, tmp_path: Path) -> None:
    test_case, run_id = _seed_test_case_and_run(isolated_db, protocol_params={})  # call_rate 없음
    fake_connector = _FakePerfSippConnector()
    executor = McpttPerformanceExecutor(
        run_id=run_id,
        settings=Settings(storage_dir=str(tmp_path / "storage")),
        ssh_target_factory=lambda: SSHTarget(host="fake-vcs"),
        sipp_ssh_target_factory=lambda: SSHTarget(host="fake-sipp"),
        sipp_ssh_connector_factory=lambda target: fake_connector,
        poll_interval_sec=0.02,
    )

    with pytest.raises(ValueError, match="call_rate"):
        await executor.run(test_case)


@pytest.mark.asyncio
async def test_uses_rate_flags_instead_of_calls_count_and_reports_stats(isolated_db, tmp_path: Path) -> None:
    test_case, run_id = _seed_test_case_and_run(
        isolated_db, protocol_params={"call_rate": 2, "rate_period_ms": 500, "max_duration_sec": 5}
    )
    fake_connector = _FakePerfSippConnector()
    executor = McpttPerformanceExecutor(
        run_id=run_id,
        settings=Settings(storage_dir=str(tmp_path / "storage")),
        ssh_target_factory=lambda: SSHTarget(host="fake-vcs"),
        sipp_ssh_target_factory=lambda: SSHTarget(host="fake-sipp"),
        sipp_ssh_connector_factory=lambda target: fake_connector,
        poll_interval_sec=0.02,
    )

    result_run = await executor.run(test_case)

    assert result_run.status == TestRunStatus.DONE
    summary = json.loads(result_run.result_summary)
    assert summary["stopped_by_user"] is False
    assert summary["call_rate"] == 2
    assert summary["rate_period_ms"] == 500
    assert summary["sipp_exit_status"] == 0
    assert summary["total_calls"] >= 1  # 샘플 로그에 RECORDING_START_RES가 있어야 함
    assert "successful_calls" in summary
    assert "achieved_call_rate_per_sec" in summary

    assert len(fake_connector.commands) == 1
    cmd = fake_connector.commands[0]
    assert "-r 2 -rp 500" in cmd
    assert " -m " not in f" {cmd} "
    assert fake_connector.closed is True


@pytest.mark.asyncio
async def test_cancelling_the_task_stops_remote_process_and_finishes_as_done(
    isolated_db, tmp_path: Path
) -> None:
    """"종료" 버튼 = job_runner.cancel() = 이 task.cancel()과 동일한 경로.
    원격 프로세스가 실제로 취소를 받고(cancelled=True), 최종 상태는 ERROR가
    아니라 DONE이어야 한다(성능 시험의 수동 종료는 정상 흐름)."""
    test_case, run_id = _seed_test_case_and_run(isolated_db, protocol_params={"call_rate": 1})
    fake_connector = _FakePerfSippConnector(hang=True)
    executor = McpttPerformanceExecutor(
        run_id=run_id,
        settings=Settings(storage_dir=str(tmp_path / "storage")),
        ssh_target_factory=lambda: SSHTarget(host="fake-vcs"),
        sipp_ssh_target_factory=lambda: SSHTarget(host="fake-sipp"),
        sipp_ssh_connector_factory=lambda target: fake_connector,
        poll_interval_sec=0.02,
    )

    task = asyncio.create_task(executor.run(test_case))
    await asyncio.sleep(0.1)  # 시뮬레이터가 "실행 중"인 상태까지 진행시킨다
    assert not task.done()

    task.cancel()
    result_run = await asyncio.wait_for(task, timeout=5)  # CancelledError가 아니라 정상 반환이어야 한다(흡수됨)

    assert fake_connector.cancelled is True
    assert fake_connector.closed is True
    assert result_run.status == TestRunStatus.DONE
    summary = json.loads(result_run.result_summary)
    assert summary["stopped_by_user"] is True
