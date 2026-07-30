"""`GET /api/test-runs/stats` 통합 테스트 (대시보드 통계 카드용 집계).

TestCase/TestRun을 직접 시딩해서 DB GROUP BY 집계 로직만 검증한다 — 실제
executor는 전혀 개입하지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models.test_case import TestCase, TestCaseCategory, TestCaseType
from app.models.test_run import TestRun, TestRunStatus


def _seed_test_case(db, category: TestCaseCategory, name: str) -> TestCase:
    test_case = TestCase(
        name=name,
        category=category,
        test_type=TestCaseType.BASIC_CALL,
        config_ref="x",
        protocol_params={},
        pass_criteria={},
    )
    db.add(test_case)
    db.commit()
    db.refresh(test_case)
    return test_case


def _seed_run(
    db, test_case_id: str, status: TestRunStatus, *, created_at: datetime | None = None
) -> TestRun:
    run = TestRun(test_case_id=test_case_id, status=status)
    db.add(run)
    db.commit()
    if created_at is not None:
        db.execute(
            TestRun.__table__.update().where(TestRun.id == run.id).values(created_at=created_at)
        )
        db.commit()
    return run


@pytest.mark.asyncio
async def test_stats_aggregates_by_status_and_category(client: httpx.AsyncClient, isolated_db) -> None:
    db = isolated_db()
    try:
        volte_case = _seed_test_case(db, TestCaseCategory.VOLTE, "volte-case")
        mcptt_case = _seed_test_case(db, TestCaseCategory.MCPTT, "mcptt-case")

        # VoLTE: 2 done, 1 failed, 1 running
        _seed_run(db, volte_case.id, TestRunStatus.DONE)
        _seed_run(db, volte_case.id, TestRunStatus.DONE)
        _seed_run(db, volte_case.id, TestRunStatus.FAILED)
        _seed_run(db, volte_case.id, TestRunStatus.RUNNING)

        # McPTT: 1 done, 1 error
        _seed_run(db, mcptt_case.id, TestRunStatus.DONE)
        _seed_run(db, mcptt_case.id, TestRunStatus.ERROR)
    finally:
        db.close()

    resp = await client.get("/api/test-runs/stats")
    assert resp.status_code == 200
    body = resp.json()

    assert body["recent_days"] == 7

    overall = body["overall"]
    assert overall["passed"] == 3
    assert overall["failed"] == 1
    assert overall["error"] == 1
    assert overall["in_progress"] == 1
    assert overall["total"] == 6
    assert overall["pass_rate"] == pytest.approx(3 / 5)  # 5건 종료(done+failed+error), running은 분모 제외

    volte_stats = body["by_category"]["volte"]
    assert volte_stats["passed"] == 2
    assert volte_stats["failed"] == 1
    assert volte_stats["in_progress"] == 1
    assert volte_stats["pass_rate"] == pytest.approx(2 / 3)

    mcptt_stats = body["by_category"]["mcptt"]
    assert mcptt_stats["passed"] == 1
    assert mcptt_stats["error"] == 1
    assert mcptt_stats["pass_rate"] == pytest.approx(1 / 2)


@pytest.mark.asyncio
async def test_stats_pass_rate_is_none_when_nothing_finished(client: httpx.AsyncClient, isolated_db) -> None:
    db = isolated_db()
    try:
        case = _seed_test_case(db, TestCaseCategory.VOLTE, "pending-only")
        _seed_run(db, case.id, TestRunStatus.PENDING)
    finally:
        db.close()

    resp = await client.get("/api/test-runs/stats")
    assert resp.status_code == 200
    body = resp.json()

    assert body["overall"]["pass_rate"] is None
    assert body["overall"]["in_progress"] == 1


@pytest.mark.asyncio
async def test_stats_excludes_old_runs_from_recent_bucket(client: httpx.AsyncClient, isolated_db) -> None:
    db = isolated_db()
    try:
        case = _seed_test_case(db, TestCaseCategory.VOLTE, "recency-case")
        _seed_run(db, case.id, TestRunStatus.DONE)  # 방금 생성 -> recent에 포함
        _seed_run(
            db, case.id, TestRunStatus.DONE, created_at=datetime.now(timezone.utc) - timedelta(days=30)
        )  # 30일 전 -> recent(7일)에서 제외
    finally:
        db.close()

    resp = await client.get("/api/test-runs/stats")
    assert resp.status_code == 200
    body = resp.json()

    assert body["overall"]["passed"] == 2  # 전체 집계에는 둘 다 포함
    assert body["recent"]["passed"] == 1  # 최근 7일 집계에는 하나만


@pytest.mark.asyncio
async def test_stats_route_does_not_shadow_run_id_route(client: httpx.AsyncClient, isolated_db) -> None:
    """`/test-runs/stats`가 `/test-runs/{run_id}`(run_id="stats")로 새지 않는지
    회귀 확인 — 라우트 등록 순서 버그가 나면 404가 뜬다."""
    resp = await client.get("/api/test-runs/stats")
    assert resp.status_code == 200
    assert "overall" in resp.json()
