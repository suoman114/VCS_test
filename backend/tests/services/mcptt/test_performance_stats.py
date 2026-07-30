"""`compute_mcptt_performance_stats()` 단위 테스트."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.call_event import CallEvent, CallEventSource
from app.services.mcptt.performance_stats import compute_mcptt_performance_stats


def _rec_event(parsed_type: str, call_id: str, *, reason_code: int | None = None, reason: str | None = None) -> CallEvent:
    reason_code_json = "null" if reason_code is None else str(reason_code)
    reason_json = "null" if reason is None else '"' + reason + '"'
    raw = (
        "-> VCMC " + parsed_type.lower() + " message send ok. [{"
        '"header": {"reasonCode": ' + reason_code_json + ', "reason": ' + reason_json + "}}]"
        " - (OutgoingMessage.java:82)"
    )
    return CallEvent(
        run_id="run-perf",
        ts=datetime.now(timezone.utc),
        source=CallEventSource.VCMM_LOG,
        parsed_type=parsed_type,
        raw_line=raw,
        call_id=call_id,
        reason_code=reason_code,
        seq_no=0,
    )


def test_counts_started_successful_failed_and_in_progress_calls() -> None:
    events = [
        _rec_event("RECORDING_START_RES", "call-1"),
        _rec_event("RECORDING_STOP_RES", "call-1", reason_code=2000, reason="Success"),
        _rec_event("RECORDING_START_RES", "call-2"),
        _rec_event("RECORDING_STOP_RES", "call-2", reason_code=500, reason="Failure"),
        _rec_event("RECORDING_START_RES", "call-3"),  # 아직 종료 안 됨
    ]

    stats = compute_mcptt_performance_stats(events, elapsed_sec=10.0)

    assert stats["total_calls"] == 3
    assert stats["successful_calls"] == 1
    assert stats["failed_calls"] == 1
    assert stats["in_progress_calls"] == 1
    assert stats["achieved_call_rate_per_sec"] == 0.3


def test_zero_elapsed_sec_does_not_divide_by_zero() -> None:
    stats = compute_mcptt_performance_stats([], elapsed_sec=0.0)
    assert stats["achieved_call_rate_per_sec"] == 0.0
    assert stats["total_calls"] == 0


def test_ignores_events_without_call_id() -> None:
    events = [_rec_event("RECORDING_START_RES", call_id="")]
    events[0].call_id = None
    stats = compute_mcptt_performance_stats(events, elapsed_sec=10.0)
    assert stats["total_calls"] == 0
