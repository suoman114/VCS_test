"""`POST /api/test-runs/{run_id}/cancel` API 통합 테스트 (2026-07-30 추가).

McPTT 성능 시험처럼 `-m`(총 호 수) 없이 무기한 실행되는 시험을 사용자가
"종료" 버튼으로 멈추는 경로. 실제 SSH/원격 프로세스는 개입시키지 않고,
`executor_registry`에 취소를 흡수해 DONE으로 정상 마무리하는 가짜
Executor를 임시 등록해 API 레벨 오케스트레이션만 검증한다.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.job_runner import job_runner
from app.models.test_run import TestRunStatus
from app.services.executor_base import TestCaseLike, TestExecutor, executor_registry


class _FakeHangingExecutor(TestExecutor):
    """취소될 때까지 무기한 대기하다가, 취소를 흡수해 DONE으로 마무리하는
    가짜 Executor — McpttPerformanceExecutor의 "종료 버튼 = 정상 완료"
    동작을 API 레벨에서 재현한다."""

    protocol = "volte"
    test_type = "basic_call"

    async def run(self, test_case: TestCaseLike):
        from app.core.database import SessionLocal
        from app.models.test_run import TestRun

        await job_runner.set_status(self.run_id, TestRunStatus.RUNNING, target_host="fake-host")
        stopped_by_user = False
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            stopped_by_user = True
        await job_runner.set_status(
            self.run_id,
            TestRunStatus.DONE,
            result_summary=json.dumps({"stopped_by_user": stopped_by_user}),
        )
        db = SessionLocal()
        try:
            return db.get(TestRun, self.run_id)
        finally:
            db.close()


async def _create_test_case(client: httpx.AsyncClient) -> str:
    payload = {
        "name": "cancel-qa-case",
        "category": "volte",
        "test_type": "basic_call",
        "config_ref": "configs/volte/basic_call_default.conf",
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
async def test_cancel_running_job_stops_it_and_finishes_as_done(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_case_id = await _create_test_case(client)
    monkeypatch.setitem(executor_registry._registry, ("volte", "basic_call"), _FakeHangingExecutor)

    resp = await client.post(f"/api/test-cases/{test_case_id}/run")
    run_id = resp.json()["id"]

    # RUNNING 상태로 전이될 때까지 잠깐 기다린다.
    for _ in range(50):
        run_resp = await client.get(f"/api/test-runs/{run_id}")
        if run_resp.json()["status"] == "running":
            break
        await asyncio.sleep(0.02)

    cancel_resp = await client.post(f"/api/test-runs/{run_id}/cancel")
    assert cancel_resp.status_code == 202, cancel_resp.text

    final_status = await _poll_until_terminal(client, run_id)
    assert final_status == "done"

    run_resp = await client.get(f"/api/test-runs/{run_id}")
    summary = json.loads(run_resp.json()["result_summary"])
    assert summary["stopped_by_user"] is True


@pytest.mark.asyncio
async def test_cancel_missing_run_404(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/test-runs/does-not-exist/cancel")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_already_finished_run_409(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.executor_base import TestCaseLike as _TCL

    class _FakeInstantDoneExecutor(TestExecutor):
        protocol = "volte"
        test_type = "basic_call"

        async def run(self, test_case: _TCL):
            from app.core.database import SessionLocal
            from app.models.test_run import TestRun

            await job_runner.set_status(self.run_id, TestRunStatus.DONE, result_summary="{}")
            db = SessionLocal()
            try:
                return db.get(TestRun, self.run_id)
            finally:
                db.close()

    test_case_id = await _create_test_case(client)
    monkeypatch.setitem(executor_registry._registry, ("volte", "basic_call"), _FakeInstantDoneExecutor)

    resp = await client.post(f"/api/test-cases/{test_case_id}/run")
    run_id = resp.json()["id"]
    await _poll_until_terminal(client, run_id)

    cancel_resp = await client.post(f"/api/test-runs/{run_id}/cancel")
    assert cancel_resp.status_code == 409
