"""`generate_mermaid()`/`generate_call_flow()` 단위 테스트 (실제 VoLTE/McPTT 성공 샘플 기반)."""
from __future__ import annotations

from app.services.callflow import detect_protocol, generate_mermaid
from app.services.callflow.generator import generate_call_flow
from app.services.log_parser import (
    VcmcLogAdapter,
    VcmmLogAdapter,
    VcsmLogAdapter,
    VctpLogAdapter,
    assign_sequence,
    parse_lines_with_adapter,
    read_file_lines,
)
from tests.services.log_parser._samples import (
    MCPTT_VCMC_LOG,
    MCPTT_VCMM_LOG,
    VOLTE_VCMM_LOG,
    VOLTE_VCSM_LOG,
    VOLTE_VCTP_LOG,
)


def _volte_events(run_id: str = "run-volte"):
    events = []
    events += parse_lines_with_adapter(VcsmLogAdapter(), read_file_lines(str(VOLTE_VCSM_LOG)), run_id=run_id)
    events += parse_lines_with_adapter(VcmmLogAdapter(), read_file_lines(str(VOLTE_VCMM_LOG)), run_id=run_id)
    events += parse_lines_with_adapter(VctpLogAdapter(), read_file_lines(str(VOLTE_VCTP_LOG)), run_id=run_id)
    return assign_sequence(events)


def _mcptt_events(run_id: str = "run-mcptt"):
    events = []
    events += parse_lines_with_adapter(VcmcLogAdapter(), read_file_lines(str(MCPTT_VCMC_LOG)), run_id=run_id)
    events += parse_lines_with_adapter(VcmmLogAdapter(), read_file_lines(str(MCPTT_VCMM_LOG)), run_id=run_id)
    return assign_sequence(events)


def test_detect_protocol() -> None:
    assert detect_protocol(_volte_events()) == "volte"
    assert detect_protocol(_mcptt_events()) == "mcptt"


def test_volte_mermaid_is_well_formed_and_excludes_vctp_relay_by_default() -> None:
    events = _volte_events()
    mermaid = generate_mermaid(events)

    assert mermaid.startswith("sequenceDiagram\n")
    # VoLTE는 실제 UE가 아니라 vctp가 pcap을 재생해 INVITE를 흘려보내는
    # 구조라 첫 참가자를 "VCTP"로 표시한다(2026-07-29, UE->VCTP 변경 요청).
    assert "participant VCTP as VCTP" in mermaid
    assert "participant VCSM as VCSM" in mermaid
    assert "participant VCMM as VCMM" in mermaid
    assert "SIP_INVITE" in mermaid
    assert "RECORDING_STOP_RES" in mermaid
    # vctp 릴레이 이벤트는 기본적으로 제외된다 (CLAUDE.md §9.1 노이즈 필터링 원칙).
    assert "VCTP_RELAY" not in mermaid

    # 모든 화살표/Note 라인이 알려진 참가자 id로 시작하는지 확인 (mermaid 구문 최소 검증).
    known_ids = {"VCTP", "VCSM", "VCMM"}
    for line in mermaid.splitlines()[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("participant"):
            continue
        first_token = stripped.split("-", 1)[0].split(" ", 1)[0]
        assert first_token in known_ids or stripped.startswith("Note over")


def test_generate_call_flow_message_index_matches_messagetext_order() -> None:
    """`.messageText` 순서와 매칭될 index가 실제 화살표 메시지 개수/순서와 일치하는지.

    Note 라인(비-SIP 참고 이벤트, 예: DURATION_CALCULATED)은 세지 않는다 —
    Mermaid에서 `.noteText`로 렌더되는 별개 클래스라 `.messageText`와 섞이지
    않기 때문이다.
    """
    events = _volte_events()
    mermaid, index = generate_call_flow(events)

    arrow_line_count = sum(
        1
        for line in mermaid.splitlines()[1:]
        if line.strip() and not line.strip().startswith(("participant", "Note over"))
    )
    assert len(index) == arrow_line_count
    assert [m.index for m in index] == list(range(len(index)))
    assert all(m.source in {"vcsm_log", "vcmm_log"} for m in index)
    assert all(m.seq_no >= 0 for m in index)


def test_mcptt_mermaid_is_well_formed() -> None:
    events = _mcptt_events()
    mermaid = generate_mermaid(events)

    assert mermaid.startswith("sequenceDiagram\n")
    assert "participant SIPp_UE as SIPp/UE" in mermaid
    assert "participant VCMC as VCMC" in mermaid
    assert "SIP_INVITE" in mermaid
    assert "RECORDING_STOP_RES" in mermaid


def test_include_vctp_relay_opt_in() -> None:
    events = _volte_events()
    mermaid = generate_mermaid(events, include_vctp_relay=True)
    assert "vctp relay" in mermaid
