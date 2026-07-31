"""`app.services.report_stats` 단위 테스트 (2026-07-30 추가, CLAUDE.md §13 TBD 해소).

콜 설정 시간 기준(recording_start_req~res)/시간별 동시 통화 수(5초 버킷,
사용자 확인) 계산 로직만 검증한다 — DB/API 레이어는
`tests/integration/test_report_stats_api.py`에서 다룬다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.call_event import CallEvent, CallEventSource
from app.services.report_stats import compute_call_setup_time_stats, compute_concurrency_time_series

_BASE_TS = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def _event(seq_no: int, parsed_type: str, call_id: str | None, offset_ms: float) -> CallEvent:
    return CallEvent(
        run_id="run-1",
        ts=_BASE_TS + timedelta(milliseconds=offset_ms),
        source=CallEventSource.VCMM_LOG,
        raw_line="",
        parsed_type=parsed_type,
        call_id=call_id,
        seq_no=seq_no,
    )


def test_setup_time_stats_returns_none_when_no_req_res_pairs() -> None:
    events = [_event(1, "SIP_INVITE", "call-1", 0)]
    assert compute_call_setup_time_stats(events) is None


def test_setup_time_stats_computes_delta_per_call() -> None:
    events = [
        _event(1, "RECORDING_START_REQ", "call-1", 0),
        _event(2, "RECORDING_START_RES", "call-1", 100),
        _event(3, "RECORDING_START_REQ", "call-2", 0),
        _event(4, "RECORDING_START_RES", "call-2", 300),
    ]
    stats = compute_call_setup_time_stats(events)
    assert stats is not None
    assert stats["count"] == 2
    assert stats["min_ms"] == 100.0
    assert stats["max_ms"] == 300.0
    assert stats["avg_ms"] == 200.0
    assert sum(bin_["count"] for bin_ in stats["histogram"]) == 2


def test_setup_time_stats_ignores_res_without_matching_req() -> None:
    """REQ가 없는 RES(예: 시험이 REQ 로그 파일이 잘려서 시작된 중간부터
    수집된 경우)는 짝을 못 찾으므로 무시돼야 한다 — 음수/엉뚱한 값 방지."""
    events = [
        _event(1, "RECORDING_START_RES", "call-orphan", 0),
        _event(2, "RECORDING_START_REQ", "call-1", 0),
        _event(3, "RECORDING_START_RES", "call-1", 50),
    ]
    stats = compute_call_setup_time_stats(events)
    assert stats is not None
    assert stats["count"] == 1
    assert stats["min_ms"] == 50.0


def test_setup_time_stats_uses_earliest_req_and_first_following_res_on_retry() -> None:
    """같은 call_id에 REQ가 두 번(재시도) 와도 가장 이른 REQ 하나만 남기고
    그 뒤 첫 RES와 짝짓는다."""
    events = [
        _event(1, "RECORDING_START_REQ", "call-1", 0),
        _event(2, "RECORDING_START_REQ", "call-1", 20),  # 재시도 REQ, 무시돼야 함
        _event(3, "RECORDING_START_RES", "call-1", 120),
    ]
    stats = compute_call_setup_time_stats(events)
    assert stats is not None
    assert stats["count"] == 1
    assert stats["min_ms"] == 120.0  # 20이 아니라 0을 기준으로 계산돼야 함


def test_concurrency_series_empty_when_no_calls_started() -> None:
    events = [_event(1, "SIP_INVITE", "call-1", 0)]
    assert compute_concurrency_time_series(events, bucket_seconds=5) == []


def test_concurrency_series_buckets_overlapping_calls() -> None:
    # call-1: 0s~12s, call-2: 3s~7s -> 버킷([0,5) [5,10) [10,15))별 동시 통화 수: 2, 2, 1
    events = [
        _event(1, "RECORDING_START_RES", "call-1", 0),
        _event(2, "RECORDING_START_RES", "call-2", 3_000),
        _event(3, "RECORDING_STOP_RES", "call-2", 7_000),
        _event(4, "RECORDING_STOP_RES", "call-1", 12_000),
    ]
    series = compute_concurrency_time_series(events, bucket_seconds=5)
    assert [p["offset_sec"] for p in series] == [0, 5, 10]
    assert [p["concurrent_calls"] for p in series] == [2, 2, 1]


def test_concurrency_series_treats_unfinished_call_as_alive_until_last_event() -> None:
    """recording_stop_res가 없는 콜(시험이 도중에 취소된 경우 등)은 이 run의
    마지막 이벤트 시각까지 살아있는 것으로 취급해 그래프가 끊기지 않는다."""
    events = [
        _event(1, "RECORDING_START_RES", "call-1", 0),
        _event(2, "SIP_BYE", "call-1", 9_000),  # stop_res 없이 시험이 끝난 상황을 흉내
    ]
    series = compute_concurrency_time_series(events, bucket_seconds=5)
    assert [p["concurrent_calls"] for p in series] == [1, 1]
