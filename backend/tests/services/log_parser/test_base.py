"""`iter_log_lines()` 공통 상태머신 단위 테스트 (합성 fixture, CLAUDE.md §9.1 그래머 기준)."""
from __future__ import annotations

from app.services.log_parser.base import CallEvent, CallEventSource, assign_sequence, iter_log_lines


def test_single_line_with_call_id_triple() -> None:
    lines = [
        "[2026-07-28 16:06:16.848][DEBUG] [nioEventLoopGroup-2-1] "
        "(B4BAC090637B72924847837C@10.64.0.54) (450281033330008) (01033330001) "
        "callInfo is create. - (CallManager.java:161)"
    ]
    (log_line,) = list(iter_log_lines(lines))

    assert log_line.call_id == "B4BAC090637B72924847837C@10.64.0.54"
    assert log_line.from_no == "450281033330008"
    assert log_line.to_no == "01033330001"
    assert log_line.class_file == "CallManager.java"
    assert log_line.line_no == 161
    assert log_line.body == "callInfo is create."


def test_single_line_without_triple_parens() -> None:
    lines = ["[2026-07-28 16:06:16.153][DEBUG] [Thread-2] [LogMonitor] start monitoring. - (LogMonitor.java:52)"]
    (log_line,) = list(iter_log_lines(lines))

    assert log_line.call_id is None
    assert log_line.from_no is None
    assert log_line.to_no is None
    assert log_line.class_file == "LogMonitor.java"


def test_multiline_block_closed_by_trailer_only_line() -> None:
    lines = [
        "[2026-07-28 16:06:16.726][INFO ] [nioEventLoopGroup-2-1] () () () "
        "NettyUdpPacket Data INVITE MESSAGE : INVITE tel:01033330001 SIP/2.0",
        "From: <sip:caller@example.com>",
        "Call-ID: ABC123",
        "",
        " - (RecordHandler.java:132)",
    ]
    (log_line,) = list(iter_log_lines(lines))

    assert log_line.class_file == "RecordHandler.java"
    assert log_line.line_no == 132
    assert log_line.body_first_line == "NettyUdpPacket Data INVITE MESSAGE : INVITE tel:01033330001 SIP/2.0"
    assert "Call-ID: ABC123" in log_line.body
    # 트레일러 직전 라인이 빈 문자열이면 body에 빈 줄로 남는다(SDP 공백 라인과 동일 취급).
    assert log_line.raw.endswith(" - (RecordHandler.java:132)")


def test_multiline_block_closed_by_line_with_prefix_before_trailer() -> None:
    """vcmm.log JSON 블록처럼 트레일러 라인 앞에 내용("}]")이 붙어 있는 경우."""
    lines = [
        '[2026-07-28 16:06:17.217][INFO ] [Thread-92] (CID) () () -> recording_start_req message receive ok. [{',
        '  "header": {"type": "recording_start_req"}',
        "}] - (RmqConsumer.java:86)",
    ]
    (log_line,) = list(iter_log_lines(lines))

    assert log_line.class_file == "RmqConsumer.java"
    assert log_line.line_no == 86
    assert log_line.body.endswith("}]")
    assert log_line.call_id == "CID"


def test_unmatched_lines_are_skipped() -> None:
    lines = ["not a log line at all", "another random line"]
    assert list(iter_log_lines(lines)) == []


def test_assign_sequence_sorts_by_timestamp_across_sources() -> None:
    from datetime import datetime

    e_later = CallEvent(
        run_id="r1",
        ts=datetime(2026, 7, 28, 16, 6, 20),
        source=CallEventSource.VCMM_LOG,
        raw_line="later",
        parsed_type="RECORDING_START_RES",
        seq_no=0,
    )
    e_earlier = CallEvent(
        run_id="r1",
        ts=datetime(2026, 7, 28, 16, 6, 16),
        source=CallEventSource.VCSM_LOG,
        raw_line="earlier",
        parsed_type="SIP_INVITE",
        seq_no=0,
    )

    ordered = assign_sequence([e_later, e_earlier])

    assert [e.raw_line for e in ordered] == ["earlier", "later"]
    assert [e.seq_no for e in ordered] == [0, 1]
