"""VolteBasicCallExecutor 통합 테스트 (CLAUDE.md §3.1).

실제 SSH 연결은 하지 않는다:
- `ssh_target_factory`/`ssh_connector_factory`(executor 생성자에 이미 열려있는
  주입 지점)에 가짜 SSH 커넥터를 넣어 `run_command`(SAMPLEFILE1 sed 치환,
  vctp 정지/시작)를 흉내낸다.
- 로그 tail(`SshTailSource`)은 `app.services.volte.executor.SshTailSource`
  이름 자체를 monkeypatch해서, 실제 SSH 대신 로컬 샘플 로그 파일
  (`docs/log_samples/volte/{vcsm,vcmm}.log`)을 폴링하는 `LocalFileSource`
  기반 스텁으로 대체한다(이미 단위테스트로 검증된 `LocalFileSource`를
  재사용 — CollectorSession 자체의 저장/브로드캐스트 로직은 건드리지 않음).

이렇게 하면 `CollectorSession` -> `wait_for_completion()` ->
`evaluate_pass_fail()` -> `persist_results()`로 이어지는 실제 파이프라인을
그대로 통과시키면서도 네트워크 I/O는 전혀 발생하지 않는다.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

import app.services.volte.executor as volte_executor_module
from app.core.config import Settings
from app.models.test_case import TestCase, TestCaseCategory, TestCaseType
from app.models.test_run import TestRun, TestRunStatus
from app.services.log_collector.base import LogSource
from app.services.log_collector.local_source import LocalFileSource
from app.services.ssh_connector.client import CommandResult, SSHTarget
from app.services.volte.executor import VolteBasicCallExecutor

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VOLTE_VCSM_LOG = _REPO_ROOT / "docs" / "log_samples" / "volte" / "vcsm.log"
_VOLTE_VCMM_LOG = _REPO_ROOT / "docs" / "log_samples" / "volte" / "vcmm.log"
_VOLTE_VCTP_LOG = _REPO_ROOT / "docs" / "log_samples" / "volte" / "vctp.log"


class _LocalTailStub(LogSource):
    """`SshTailSource`를 대체하는 스텁: 실제 SSH 대신 로컬 파일을 tail한다.

    executor가 `SshTailSource(name, path, target=target)` 시그니처로 호출하므로
    동일한 생성자 시그니처를 유지하되 `target`은 무시한다.
    """

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


class _FakeSSHConnector:
    """`run_command`/`close`만 성공 응답을 흉내내는 가짜 SSH 커넥터.

    VoLTE 실행기는 더 이상 파일을 업로드하지 않는다(pcap 샘플은 이미 VCS에
    있고, SAMPLEFILE1을 sed로 바꿀 뿐이다) — 그래서 `upload_file`은 정의하지
    않는다. 만약 executor가 실수로 다시 호출하면 AttributeError로 즉시 드러난다.
    """

    def __init__(self, target: SSHTarget) -> None:
        self.target = target
        self.commands: list[str] = []

    async def run_command(self, command: str) -> CommandResult:
        self.commands.append(command)
        return CommandResult(command=command, exit_status=0, stdout="ok", stderr="")

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _local_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(volte_executor_module, "SshTailSource", _LocalTailStub)


def _seed_test_case_and_run(isolated_db) -> tuple[TestCase, str]:
    db = isolated_db()
    try:
        test_case = TestCase(
            name="volte-executor-qa-fixture",
            category=TestCaseCategory.VOLTE,
            test_type=TestCaseType.BASIC_CALL,
            config_ref="imsVideo30sec.pcap",
            protocol_params={
                "sample_file": "imsVideo30sec.pcap",
                "vcsm_log_path": str(_VOLTE_VCSM_LOG),
                "vcmm_log_path": str(_VOLTE_VCMM_LOG),
                "vctp_log_path": str(_VOLTE_VCTP_LOG),
                "timeout_sec": 5,
            },
            pass_criteria={},
        )
        db.add(test_case)
        db.commit()
        db.refresh(test_case)
        # 커밋은 세션 내 모든 객체의 속성을 만료(expire)시킨다. 아래에서 test_run을
        # 커밋하기 전에 test_case를 세션에서 분리해야, 이후 (별도 세션에서 실행되는)
        # executor.run()이 detached 상태에서도 이미 로드된 속성 값을 그대로 쓸 수 있다.
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
async def test_volte_executor_run_passes_with_sample_logs(isolated_db, tmp_path: Path) -> None:
    test_case, run_id = _seed_test_case_and_run(isolated_db)
    fake_connector = _FakeSSHConnector(SSHTarget(host="fake-vcs"))
    # storage_dir을 tmp_path로 격리해 repo의 실제 storage/logs/를 오염시키지 않는다.
    isolated_settings = Settings(storage_dir=str(tmp_path / "storage"))

    executor = VolteBasicCallExecutor(
        run_id=run_id,
        settings=isolated_settings,
        ssh_target_factory=lambda: SSHTarget(host="fake-vcs"),
        ssh_connector_factory=lambda target: fake_connector,
    )

    result_run = await executor.run(test_case)

    assert result_run.status == TestRunStatus.DONE
    assert result_run.result_summary is not None
    summary = json.loads(result_run.result_summary)
    assert summary["passed"] is True, summary["reasons"]
    assert summary["event_count"] > 0
    assert summary["timed_out"] is False

    # CLAUDE.md §3.1 1~2단계: SAMPLEFILE1 치환(sed) + vctp 정지/시작 명령이 순서대로 호출됐는지.
    assert len(fake_connector.commands) == 3
    sed_cmd, stop_cmd, start_cmd = fake_connector.commands
    assert "sed -i -E" in sed_cmd
    assert "SAMPLEFILE1" in sed_cmd
    assert "imsVideo30sec.pcap" in sed_cmd
    assert isolated_settings.vctp_config_path in sed_cmd
    assert stop_cmd == isolated_settings.vctp_stop_cmd
    assert start_cmd == isolated_settings.vctp_start_cmd

    assert result_run.target_host == "fake-vcs"
    assert result_run.raw_log_path is not None
