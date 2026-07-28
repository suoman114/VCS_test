"""`generate_mermaid()` 단위 테스트 (실제 VoLTE/McPTT 성공 샘플 기반)."""
from __future__ import annotations

from app.services.callflow import detect_protocol, generate_mermaid
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
    assert "participant UE as UE" in mermaid
    assert "participant VCS as VCS(vctp/vcsm)" in mermaid
    assert "participant VCMM as VCMM" in mermaid
    assert "SIP_INVITE" in mermaid
    assert "RECORDING_STOP_RES" in mermaid
    # vctp 릴레이 이벤트는 기본적으로 제외된다 (CLAUDE.md §9.1 노이즈 필터링 원칙).
    assert "VCTP_RELAY" not in mermaid

    # 모든 화살표/Note 라인이 알려진 참가자 id로 시작하는지 확인 (mermaid 구문 최소 검증).
    known_ids = {"UE", "VCS", "VCMM"}
    for line in mermaid.splitlines()[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("participant"):
            continue
        first_token = stripped.split("-", 1)[0].split(" ", 1)[0]
        assert first_token in known_ids or stripped.startswith("Note over")


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
