"""`GET /test-runs/{id}/report-stats` 통합 테스트 (2026-07-30 추가).

콜 설정 시간 분포 / 시간별 동시 통화 수(CLAUDE.md §13 TBD 해소) 엔드포인트가
DB에 저장된 CallEvent로부터 올바르게 계산해 내려주는지 확인한다. 계산
로직 자체의 세부 케이스는 `tests/services/test_report_stats.py`에서 다룬다
— 여기서는 API 경계(라우팅, 404, 쿼리 파라미터, 응답 스키마)만 확인한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from app.models.call_event import CallEvent, CallEventSource
from app.models.test_case import TestCase, TestCaseCategory, TestCaseType
from app.models.test_run import TestRun, TestRunStatus

_BASE_TS = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def _event(run_id: str, seq_no: int, parsed_type: str, call_id: str, offset_ms: float) -> CallEvent:
    return CallEvent(
        run_id=run_id,
        ts=_BASE_TS + timedelta(milliseconds=offset_ms),
        source=CallEventSource.VCMM_LOG,
        raw_line="",
        parsed_type=parsed_type,
        call_id=call_id,
        seq_no=seq_no,
    )


@pytest.mark.asyncio
async def test_report_stats_returns_setup_time_and_concurrency(
    client: httpx.AsyncClient, isolated_db
) -> None:
    run_id = "run-report-stats"
    db = isolated_db()
    try:
        test_case = TestCase(
            id="tc-report-stats",
            name="report-stats-fixture",
            category=TestCaseCategory.MCPTT,
            test_type=TestCaseType.PERFORMANCE,
            config_ref="mcptt_basic_call.xml",
            protocol_params={},
            pass_criteria={},
        )
        db.add(test_case)
        db.add(TestRun(id=run_id, test_case_id=test_case.id, status=TestRunStatus.DONE))
        # call-1: REQ~RES 100ms, 0s~6s 진행. call-2: REQ~RES 300ms, 2s~4s 진행.
        db.add(_event(run_id, 1, "RECORDING_START_REQ", "call-1", 0))
        db.add(_event(run_id, 2, "RECORDING_START_RES", "call-1", 100))
        db.add(_event(run_id, 3, "RECORDING_START_REQ", "call-2", 2_000))
        db.add(_event(run_id, 4, "RECORDING_START_RES", "call-2", 2_300))
        db.add(_event(run_id, 5, "RECORDING_STOP_RES", "call-2", 4_000))
        db.add(_event(run_id, 6, "RECORDING_STOP_RES", "call-1", 6_000))
        db.commit()
    finally:
        db.close()

    resp = await client.get(f"/api/test-runs/{run_id}/report-stats")
    assert resp.status_code == 200
    body = resp.json()

    assert body["bucket_seconds"] == 5
    assert body["setup_time"]["count"] == 2
    assert body["setup_time"]["min_ms"] == 100.0
    assert body["setup_time"]["max_ms"] == 300.0
    assert len(body["setup_time"]["histogram"]) == 10

    # 버킷: [0,5) -> call-1(0~6s) + call-2(2~4s) 둘 다 겹침 = 2, [5,10) -> call-1만 = 1
    assert body["concurrency_series"] == [
        {"offset_sec": 0, "concurrent_calls": 2},
        {"offset_sec": 5, "concurrent_calls": 1},
    ]


@pytest.mark.asyncio
async def test_report_stats_setup_time_null_when_no_recording_events(
    client: httpx.AsyncClient, isolated_db
) -> None:
    run_id = "run-report-stats-empty"
    db = isolated_db()
    try:
        test_case = TestCase(
            id="tc-report-stats-empty",
            name="report-stats-empty-fixture",
            category=TestCaseCategory.VOLTE,
            test_type=TestCaseType.BASIC_CALL,
            config_ref="imsVideo30sec.pcap",
            protocol_params={},
            pass_criteria={},
        )
        db.add(test_case)
        db.add(TestRun(id=run_id, test_case_id=test_case.id, status=TestRunStatus.DONE))
        db.add(_event(run_id, 1, "SIP_INVITE", "call-1", 0))
        db.commit()
    finally:
        db.close()

    resp = await client.get(f"/api/test-runs/{run_id}/report-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["setup_time"] is None
    assert body["concurrency_series"] == []


@pytest.mark.asyncio
async def test_report_stats_accepts_custom_bucket_seconds(client: httpx.AsyncClient, isolated_db) -> None:
    run_id = "run-report-stats-bucket"
    db = isolated_db()
    try:
        test_case = TestCase(
            id="tc-report-stats-bucket",
            name="report-stats-bucket-fixture",
            category=TestCaseCategory.MCPTT,
            test_type=TestCaseType.PERFORMANCE,
            config_ref="mcptt_basic_call.xml",
            protocol_params={},
            pass_criteria={},
        )
        db.add(test_case)
        db.add(TestRun(id=run_id, test_case_id=test_case.id, status=TestRunStatus.DONE))
        db.add(_event(run_id, 1, "RECORDING_START_RES", "call-1", 0))
        db.add(_event(run_id, 2, "RECORDING_STOP_RES", "call-1", 10_000))
        db.commit()
    finally:
        db.close()

    resp = await client.get(f"/api/test-runs/{run_id}/report-stats", params={"bucket_seconds": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket_seconds"] == 10
    assert body["concurrency_series"] == [
        {"offset_sec": 0, "concurrent_calls": 1},
        {"offset_sec": 10, "concurrent_calls": 1},
    ]


@pytest.mark.asyncio
async def test_report_stats_404s_for_unknown_run(client: httpx.AsyncClient, isolated_db) -> None:
    resp = await client.get("/api/test-runs/does-not-exist/report-stats")
    assert resp.status_code == 404
