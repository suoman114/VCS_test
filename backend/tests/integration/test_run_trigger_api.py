"""`POST /api/test-cases/{id}/run` -> `GET /api/test-runs/{id}` API 통합 테스트
(CLAUDE.md §3.3, §8-2).

두 경로를 모두 검증한다:
1. 성공 경로 - executor 자체는 무겁게 재현하지 않고(이미 test_volte_executor.py
   /test_mcptt_executor.py에서 검증됨), `executor_registry`에 가벼운 가짜
   Executor를 임시 등록해 API 레벨 오케스트레이션(즉시 pending 응답 ->
   백그라운드 job -> 상태 전이 -> 조회 API)만 검증한다.
2. 실패 경로 - 실제 `VolteBasicCallExecutor`를 그대로 쓰되, VCS SSH 접속
   정보(`VCS_SSH_HOST`)가 설정되지 않은 기본 상태이므로
   `SSHTarget.from_vcs_settings()`가 `ValueError`를 던지고, 이를
   `job_runner._run_wrapper`가 잡아 `TestRunStatus.ERROR`로 전이시키는지
   확인한다(실제 장비 접근 없이 SSH 실패 케이스를 검증).
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.job_runner import job_runner
from app.models.test_run import TestRunStatus
from app.services.executor_base import TestExecutor, TestCaseLike, executor_registry


class _FakeDoneExecutor(TestExecutor):
    """SSH/SIPp를 전혀 건드리지 않고 즉시 DONE으로 전이하는 가짜 Executor."""

    protocol = "volte"
    test_type = "basic_call"

    async def run(self, test_case: TestCaseLike):
        from app.core.database import SessionLocal
        from app.models.test_run import TestRun

        await job_runner.set_status(self.run_id, TestRunStatus.RUNNING, target_host="fake-host")
        await asyncio.sleep(0)  # 다른 태스크에 제어권을 한 번 넘겨 비동기 job임을 반영
        await job_runner.set_status(
            self.run_id,
            TestRunStatus.DONE,
            result_summary=json.dumps(
                {"passed": True, "reasons": ["fake executor"], "timed_out": False, "event_count": 0}
            ),
        )
        db = SessionLocal()
        try:
            return db.get(TestRun, self.run_id)
        finally:
            db.close()


async def _create_test_case(client: httpx.AsyncClient, *, category: str = "volte") -> str:
    payload = {
        "name": f"trigger-qa-{category}",
        "category": category,
        "test_type": "basic_call",
        "config_ref": (
            "configs/volte/basic_call_default.conf"
            if category == "volte"
            else "scenarios/sipp/mcptt_basic_call.xml"
        ),
        "protocol_params": {},
        "pass_criteria": {},
    }
    resp = await client.post("/api/test-cases", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _poll_until_terminal(client: httpx.AsyncClient, run_id: str, *, attempts: int = 100) -> str:
    status_value = "pending"
    for _ in range(attempts):
        resp = await client.get(f"/api/test-runs/{run_id}")
        assert resp.status_code == 200
        status_value = resp.json()["status"]
        if status_value in ("done", "failed", "error"):
            return status_value
        await asyncio.sleep(0.02)
    return status_value


@pytest.mark.asyncio
async def test_trigger_run_returns_pending_immediately(client: httpx.AsyncClient) -> None:
    test_case_id = await _create_test_case(client)

    resp = await client.post(f"/api/test-cases/{test_case_id}/run")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["test_case_id"] == test_case_id


@pytest.mark.asyncio
async def test_trigger_run_success_flow_with_fake_executor(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_case_id = await _create_test_case(client)
    monkeypatch.setitem(executor_registry._registry, ("volte", "basic_call"), _FakeDoneExecutor)

    resp = await client.post(f"/api/test-cases/{test_case_id}/run")
    assert resp.status_code == 202
    run_id = resp.json()["id"]

    final_status = await _poll_until_terminal(client, run_id)
    assert final_status == "done"

    run_resp = await client.get(f"/api/test-runs/{run_id}")
    summary = json.loads(run_resp.json()["result_summary"])
    assert summary["passed"] is True

    events_resp = await client.get(f"/api/test-runs/{run_id}/events")
    assert events_resp.status_code == 200
    assert events_resp.json()["total"] == 0  # 가짜 executor는 CallEvent를 만들지 않음


@pytest.mark.asyncio
async def test_trigger_run_ssh_failure_transitions_to_error(client: httpx.AsyncClient) -> None:
    """CLAUDE.md §3.1: VCS_SSH_HOST 미설정 상태에서는 SSH 연결 자체가 실패해야 한다."""
    test_case_id = await _create_test_case(client)

    resp = await client.post(f"/api/test-cases/{test_case_id}/run")
    assert resp.status_code == 202
    run_id = resp.json()["id"]

    final_status = await _poll_until_terminal(client, run_id)
    assert final_status == "error"


@pytest.mark.asyncio
async def test_trigger_run_missing_test_case_404(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/test-cases/does-not-exist/run")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_call_flow_not_found_before_run(client: httpx.AsyncClient) -> None:
    test_case_id = await _create_test_case(client)
    resp = await client.post(f"/api/test-cases/{test_case_id}/run")
    run_id = resp.json()["id"]

    # 아직 파싱/판정이 끝나지 않았을 시점(트리거 직후)에는 call-flow가 없어야 한다.
    cf_resp = await client.get(f"/api/test-runs/{run_id}/call-flow")
    assert cf_resp.status_code == 404
