"""파싱된 `CallEvent` 시퀀스 -> Mermaid `sequenceDiagram` 텍스트 변환
(CLAUDE.md §4, §9).

참가자(Participant)는 프로토콜에 따라 동적으로 결정한다:
    VoLTE : VCTP <-> VCSM <-> VCMM
    McPTT : SIPp/UE <-> VCMC <-> VCMM

VoLTE는 실제 사용자 단말(UE)이 아니라 vctp가 사전 캡처된 pcap을 재생
(replay)해서 INVITE 등을 흘려보내는 구조라(CLAUDE.md §3.1), 첫 참가자를
추상적인 "UE"가 아니라 실제 트래픽 유입 지점인 "VCTP"로 표시한다(2026-07-29
사용자 피드백 반영). vctp가 릴레이하는 SIP 메시지 자체(`vctp.log`)는 여전히
vcsm.log와 사실상 중복이라 기본 렌더링에서는 제외하고(§9.1),
`include_vctp_relay=True`일 때만 VCTP 레인에 각주(Note)로 참고 표시한다.

방향(화살표) 추론은 CallEvent 스키마에 별도 컬럼이 없으므로, 어댑터가
보존해둔 `raw_line`(원본 블록 전체)을 이 모듈에서 다시 정규식으로
살펴봐서 판단한다 — DB 스키마를 변경하지 않고도 참가자 추론 로직을 독립적으로
개선할 수 있게 하기 위함이다 (예: vcsm의 요청/응답 근사 규칙은 TODO로
문서화된 한계가 있다. `vcsm_adapter.py` 참고).

`generate_call_flow()`는 Mermaid 텍스트와 함께, 렌더링된 메시지(화살표) 각각이
어떤 CallEvent(seq_no/source)에서 나왔는지 순서대로 담은 `CallFlowMessageRef`
목록도 반환한다 — 프론트가 Call Flow에서 메시지를 클릭했을 때 대응하는 로그로
바로 이동하는 기능(2026-07-29 요청)에 쓰인다. Mermaid가 각 메시지 라벨에
`.messageText` CSS 클래스를 순서대로 부여하므로(Note는 `.noteText`라 섞이지
않음), 프론트는 렌더된 `.messageText` 엘리먼트 순번과 이 목록의 `index`를
그대로 매칭하면 된다. `generate_mermaid()`는 기존 호출부(단순 텍스트만
필요한 곳)를 위해 남겨둔 얇은 래퍼다.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.models.call_event import CallEvent, CallEventSource

Protocol = Literal["volte", "mcptt"]

_VCTP = "VCTP"
_VCSM = "VCSM"
_SIPP_UE = "SIPp_UE"
_VCMC = "VCMC"
_VCMM = "VCMM"

_PARTICIPANTS: dict[Protocol, list[tuple[str, str]]] = {
    # (id, mermaid label)
    "volte": [(_VCTP, "VCTP"), (_VCSM, "VCSM"), (_VCMM, "VCMM")],
    "mcptt": [(_SIPP_UE, "SIPp/UE"), (_VCMC, "VCMC"), (_VCMM, "VCMM")],
}

_IS_SENDER_RE = re.compile(r'isSender="(?P<val>true|false)"')
_MSG_FROM_RE = re.compile(r'"msgFrom":\s*"(?P<val>[^"]+)"')
_MESSAGE_ACTION_RE = re.compile(r"message\s+(?P<action>receive|send)\s+ok\.")


@dataclass(frozen=True)
class CallFlowMessageRef:
    """Mermaid 다이어그램의 메시지(화살표) 하나 -> 원본 CallEvent 참조.

    `index`는 실제로 렌더되는 메시지(화살표)만 0부터 센 순번이다(Note/
    participant 선언 줄은 세지 않음) — 렌더된 SVG의 `.messageText` 순서와
    1:1로 대응한다.
    """

    index: int
    seq_no: int
    source: str
    call_id: str | None


def detect_protocol(events: Sequence[CallEvent]) -> Protocol:
    """이벤트에 포함된 `source`로 프로토콜을 판별한다.

    vcmc_log가 하나라도 있으면 McPTT, 그렇지 않으면(vcsm_log/vctp_log 등)
    VoLTE로 간주한다. 두 소스가 섞여 있는 경우는 현재 샘플 범위 밖이라
    McPTT를 우선한다(McPTT가 vcmc+vcmm 조합이라 더 구체적인 신호이므로).
    """
    sources = {e.source for e in events}
    if CallEventSource.VCMC_LOG in sources or CallEventSource.SIPP_LOG in sources:
        return "mcptt"
    return "volte"


def _sanitize_label(text: str) -> str:
    # Mermaid sequenceDiagram 라벨에서 문제되는 문자만 최소한으로 치환.
    return text.replace(":", "#58;").replace("\n", " ").strip()


def _edge_for_vcsm(event: CallEvent) -> tuple[str, str] | None:
    """TODO(근사): vcsm 블록에는 vcmc의 isSender 같은 명시적 방향 필드가
    없다. SIP 요청(Request-Line)은 VCTP->VCSM, 응답(Status-Line)은
    VCSM->VCTP로 근사한다. 실패/에러 케이스 로그로 재검증 전까지는
    근사치임을 유지한다.
    """
    if event.reason_code is not None:  # 응답(상태코드)
        return _VCSM, _VCTP
    return _VCTP, _VCSM


def _edge_for_vcmc(event: CallEvent) -> tuple[str, str] | None:
    m = _IS_SENDER_RE.search(event.raw_line)
    if m is None:
        return None
    if m.group("val") == "true":
        return _VCMC, _SIPP_UE
    return _SIPP_UE, _VCMC


def _edge_for_vcmm(event: CallEvent, protocol: Protocol) -> tuple[str, str] | None:
    action_m = _MESSAGE_ACTION_RE.search(event.raw_line)
    if action_m is None:
        return None
    peer = _VCSM if protocol == "volte" else _VCMC
    if action_m.group("action") == "receive":
        return peer, _VCMM
    return _VCMM, peer


def _event_label(event: CallEvent) -> str:
    return _sanitize_label(event.parsed_type)


def _build_lines_and_index(
    events: Sequence[CallEvent], proto: Protocol, include_vctp_relay: bool
) -> tuple[list[str], list[CallFlowMessageRef]]:
    ordered = sorted(events, key=lambda e: e.seq_no)

    lines: list[str] = ["sequenceDiagram"]
    for pid, label in _PARTICIPANTS[proto]:
        lines.append(f"    participant {pid} as {label}")

    index: list[CallFlowMessageRef] = []
    for event in ordered:
        if event.source == CallEventSource.VCTP_LOG:
            if include_vctp_relay:
                lines.append(f"    Note over {_VCTP}: (vctp relay) {_event_label(event)}")
            continue

        if not event.parsed_type.startswith("SIP_") and event.source in (
            CallEventSource.VCSM_LOG,
            CallEventSource.VCMC_LOG,
        ):
            # SIP 이벤트가 아닌 참고성 이벤트(예: vcsm의 DURATION_CALCULATED)는
            # 화살표 대신 각주(Note)로만 표시한다.
            lane = _VCSM if event.source == CallEventSource.VCSM_LOG else _VCMC
            lines.append(f"    Note over {lane}: {_event_label(event)}")
            continue

        edge: tuple[str, str] | None
        if event.source == CallEventSource.VCSM_LOG:
            edge = _edge_for_vcsm(event)
        elif event.source == CallEventSource.VCMC_LOG:
            edge = _edge_for_vcmc(event)
        elif event.source == CallEventSource.VCMM_LOG:
            edge = _edge_for_vcmm(event, proto)
        else:
            # sipp_log 등 아직 어댑터가 없는 소스 (TODO, sipp_adapter.py 참고)
            edge = None

        if edge is None:
            continue

        src, dst = edge
        arrow = "-->>" if (event.reason_code is not None or event.parsed_type.endswith("_RES")) else "->>"
        lines.append(f"    {src}{arrow}{dst}: {_event_label(event)}")
        index.append(
            CallFlowMessageRef(
                index=len(index),
                seq_no=event.seq_no,
                source=event.source.value,
                call_id=event.call_id,
            )
        )

    return lines, index


def generate_mermaid(
    events: Sequence[CallEvent],
    protocol: Protocol | None = None,
    include_vctp_relay: bool = False,
) -> str:
    """`CallEvent` 시퀀스를 Mermaid `sequenceDiagram` 텍스트로 변환한다.

    `events`는 이미 시간순으로 정렬되어 있다고 가정한다
    (`app.services.log_parser.base.assign_sequence` 참고). 이 함수 자체는
    안전을 위해 `seq_no` 기준으로 재정렬한다. 메시지-이벤트 매핑까지
    필요하면 `generate_call_flow()`를 대신 쓴다.
    """
    proto = protocol or detect_protocol(events)
    lines, _ = _build_lines_and_index(events, proto, include_vctp_relay)
    return "\n".join(lines) + "\n"


def generate_call_flow(
    events: Sequence[CallEvent],
    protocol: Protocol | None = None,
    include_vctp_relay: bool = False,
) -> tuple[str, list[CallFlowMessageRef]]:
    """Mermaid 텍스트 + 메시지별 원본 CallEvent 참조를 함께 생성한다."""
    proto = protocol or detect_protocol(events)
    lines, index = _build_lines_and_index(events, proto, include_vctp_relay)
    return "\n".join(lines) + "\n", index
