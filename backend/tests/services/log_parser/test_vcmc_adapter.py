"""VcmcLogAdapter 단위 테스트 (실제 `docs/log_samples/mcptt/vcmc.log` 사용)."""
from __future__ import annotations

from app.services.log_parser import VcmcLogAdapter, read_file_lines
from tests.services.log_parser._samples import MCPTT_VCMC_LOG

_CALL_ID = "960e2eb1475c0fca01edff976528e956@192.168.7.65_1"


def test_parses_invite_with_is_sender_false() -> None:
    adapter = VcmcLogAdapter()
    events = list(adapter.parse(read_file_lines(str(MCPTT_VCMC_LOG))))

    assert len(events) > 0
    invite = next(e for e in events if e.parsed_type == "SIP_INVITE")
    assert invite.call_id == _CALL_ID
    assert invite.reason_code is None
    assert 'isSender="false"' in invite.raw_line


def test_parses_responses_and_bye() -> None:
    adapter = VcmcLogAdapter()
    events = list(adapter.parse(read_file_lines(str(MCPTT_VCMC_LOG))))

    parsed_types = [e.parsed_type for e in events]
    assert "SIP_100" in parsed_types
    assert "SIP_180" in parsed_types
    assert "SIP_200" in parsed_types
    assert "SIP_ACK" in parsed_types
    assert "SIP_BYE" in parsed_types

    ok_200 = next(e for e in events if e.parsed_type == "SIP_200")
    assert ok_200.reason_code == 200
    assert 'isSender="true"' in ok_200.raw_line  # vcmc가 응답을 발신
