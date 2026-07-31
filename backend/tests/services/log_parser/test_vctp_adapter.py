"""VctpLogAdapter 단위 테스트 (실제 `docs/log_samples/volte/vctp.log` 사용)."""
from __future__ import annotations

from app.services.log_parser import VctpLogAdapter, read_file_lines
from tests.services.log_parser._samples import VOLTE_VCTP_LOG


def test_filters_rtp_relay_noise_and_keeps_sip_relay_reference() -> None:
    adapter = VctpLogAdapter()
    events = list(adapter.parse(read_file_lines(str(VOLTE_VCTP_LOG))))

    # 샘플은 8972줄 중 8866줄이 DumpPacketTask.java:156(RTP relay) 노이즈다.
    # 어댑터는 이를 전부 걸러내고 SIP relay 참고 라인(:131)만 남겨야 한다.
    assert len(events) > 0
    assert len(events) < 100  # 노이즈(수천 건)가 섞여 들어오면 안 된다.

    first = events[0]
    assert first.parsed_type == "VCTP_RELAY_SIP_INVITE"
    assert first.call_id is None  # vctp 릴레이 라인에는 Call-ID가 없음 (문서화된 한계)

    parsed_types = {e.parsed_type for e in events}
    assert "VCTP_RELAY_SIP_200" in parsed_types
    assert "VCTP_RELAY_SIP_BYE" in parsed_types
