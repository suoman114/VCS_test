"""VcmcLogAdapter 단위 테스트 (실제 `docs/log_samples/mcptt/vcmc.log` 사용)."""
from __future__ import annotations

from app.services.log_parser import VcmcLogAdapter, read_file_lines
from tests.services.log_parser._samples import MCPTT_VCMC_LOG, MCPTT_VCMC_LOG_FORMAT_B

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


_FORMAT_B_CALL_ID = "564494afddcdf642271a2651813cbbbd@192.168.7.65_1"


def test_parses_format_b_invite_and_bye() -> None:
    """2026-07-30 실 서버 리포트: vcmc.log에 INVITE가 들어오는데 Call Flow에
    안 보임 — 원인은 이 어댑터가 `<message>` XML 래퍼 포맷(포맷 A)만 지원해서,
    실 서버가 실제로 쓰는 `[SIP] INCOMING|OUTGOING REQUEST|RESPONSE [...]`
    포맷(포맷 B)의 메시지는 애초에 이벤트로 파싱조차 안 됐던 것이었다.
    사용자가 제공한 실 서버 캡처(`vcmc_format_b.log`)로 회귀를 잡는다."""
    adapter = VcmcLogAdapter()
    events = list(adapter.parse(read_file_lines(str(MCPTT_VCMC_LOG_FORMAT_B))))

    parsed_types = [e.parsed_type for e in events]
    assert parsed_types == ["SIP_INVITE", "SIP_100", "SIP_180", "SIP_200", "SIP_ACK", "SIP_ACK", "SIP_BYE", "SIP_200"]
    assert all(e.call_id == _FORMAT_B_CALL_ID for e in events)

    invite = events[0]
    assert invite.reason_code is None
    assert invite.extra["is_sender"] == "false"  # INCOMING REQUEST -> vcmc가 수신

    ok_100 = events[1]
    assert ok_100.reason_code == 100
    assert ok_100.extra["is_sender"] == "true"  # OUTGOING RESPONSE -> vcmc가 발신

    bye = events[6]
    assert bye.parsed_type == "SIP_BYE"
    assert bye.extra["is_sender"] == "false"
