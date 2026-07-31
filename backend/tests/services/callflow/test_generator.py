"""`generate_mermaid()`/`generate_call_flow()` 단위 테스트 (실제 VoLTE/McPTT 성공 샘플 기반)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.call_event import CallEvent, CallEventSource
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
    MCPTT_VCMC_LOG_FORMAT_B,
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


def test_mcptt_mermaid_renders_invite_and_bye_for_vcmc_format_b() -> None:
    """2026-07-30 실 서버 캡처(vcmc.log 포맷 B) 기반 회귀 — INVITE/BYE가
    Call Flow 화살표로 실제 렌더링되는지 종단 확인(어댑터 파싱 +
    generator 방향 판단 둘 다)."""
    events = []
    events += parse_lines_with_adapter(
        VcmcLogAdapter(), read_file_lines(str(MCPTT_VCMC_LOG_FORMAT_B)), run_id="run-mcptt-b"
    )
    events += parse_lines_with_adapter(
        VcmmLogAdapter(), read_file_lines(str(MCPTT_VCMM_LOG)), run_id="run-mcptt-b"
    )
    events = assign_sequence(events)

    mermaid = generate_mermaid(events, protocol="mcptt")

    assert "SIPp_UE->>VCMC: SIP_INVITE" in mermaid
    assert "SIPp_UE->>VCMC: SIP_BYE" in mermaid
    assert "VCMC-->>SIPp_UE: SIP_200" in mermaid


def test_include_vctp_relay_opt_in() -> None:
    events = _volte_events()
    mermaid = generate_mermaid(events, include_vctp_relay=True)
    assert "vctp relay" in mermaid


def test_mcptt_vcmc_event_still_renders_when_is_sender_attribute_missing() -> None:
    """2026-07-30 실 서버 리포트: vcmc.log에 INVITE가 들어오는데 Call Flow에
    안 보이는 문제. `_edge_for_vcmc`가 `isSender` 속성을 raw_line에서 못
    찾으면(원인 불문 — 로그 포맷 변형, 파싱 경계 등) 예전엔 해당 메시지를
    통째로 버렸다 — 요청(INVITE/BYE, reason_code 없음)과 응답(200 OK 등,
    reason_code 있음) 둘 다 최소한 화면에는 보여야 한다(방향은 근사치)."""
    invite = CallEvent(
        run_id="run-1",
        ts=datetime(2026, 7, 30, 1, 0, 0, tzinfo=timezone.utc),
        source=CallEventSource.VCMC_LOG,
        parsed_type="SIP_INVITE",
        raw_line="<message\ncallId=\"abc\"\nfirstLine=\"INVITE sip:foo SIP/2.0\"\n>\n<![CDATA[...]]>\n</message>",
        call_id="abc",
        reason_code=None,
        seq_no=0,
    )
    ok_200 = CallEvent(
        run_id="run-1",
        ts=datetime(2026, 7, 30, 1, 0, 1, tzinfo=timezone.utc),
        source=CallEventSource.VCMC_LOG,
        parsed_type="SIP_200",
        raw_line="<message\ncallId=\"abc\"\nfirstLine=\"SIP/2.0 200 OK\"\n>\n<![CDATA[...]]>\n</message>",
        call_id="abc",
        reason_code=200,
        seq_no=1,
    )

    mermaid = generate_mermaid([invite, ok_200], protocol="mcptt")

    assert "SIPp_UE->>VCMC: SIP_INVITE" in mermaid
    assert "VCMC-->>SIPp_UE: SIP_200" in mermaid
