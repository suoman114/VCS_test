"""VcsmLogAdapter 단위 테스트 (실제 `docs/log_samples/volte/vcsm.log` 사용)."""
from __future__ import annotations

from app.services.log_parser import VcsmLogAdapter, read_file_lines
from tests.services.log_parser._samples import VOLTE_VCSM_LOG

_CALLER_CALL_ID = "B4BAC090637B72924847837C@10.64.0.54"


def test_parses_initial_invite_with_call_id() -> None:
    adapter = VcsmLogAdapter()
    events = list(adapter.parse(read_file_lines(str(VOLTE_VCSM_LOG))))

    assert len(events) > 0
    first_invite = next(e for e in events if e.parsed_type == "SIP_INVITE")
    assert first_invite.call_id == _CALLER_CALL_ID
    assert first_invite.reason_code is None
    # 원본 SIP 메시지(SDP 포함) 전체가 raw_line에 보존되어야 한다.
    assert "Call-ID: " + _CALLER_CALL_ID in first_invite.raw_line
    assert "m=audio" in first_invite.raw_line


def test_parses_sip_responses_and_bye() -> None:
    adapter = VcsmLogAdapter()
    events = list(adapter.parse(read_file_lines(str(VOLTE_VCSM_LOG))))

    parsed_types = [e.parsed_type for e in events]
    assert "SIP_200" in parsed_types
    assert "SIP_180" in parsed_types
    assert "SIP_BYE" in parsed_types

    ok_200 = next(e for e in events if e.parsed_type == "SIP_200")
    assert ok_200.reason_code == 200


def test_extracts_duration_calculated() -> None:
    adapter = VcsmLogAdapter()
    events = list(adapter.parse(read_file_lines(str(VOLTE_VCSM_LOG))))

    duration_events = [e for e in events if e.parsed_type == "DURATION_CALCULATED"]
    assert len(duration_events) >= 1
    assert "Duration calculated:" in duration_events[0].raw_line
