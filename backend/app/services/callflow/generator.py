"""파싱된 `CallEvent` 시퀀스 -> Mermaid `sequenceDiagram` 텍스트 변환
(CLAUDE.md §4, §9).

참가자(Participant)는 프로토콜에 따라 동적으로 결정한다:
    VoLTE : UE <-> VCS(vcsm) <-> VCMM
    McPTT : SIPp/UE <-> VCMC <-> VCMM

CLAUDE.md §9.1에 따라 `vctp.log` 이벤트(`VCTP_RELAY_SIP_*`)는 vcsm.log와
사실상 중복되는 저비중 참고 정보이므로 **기본 Call Flow 렌더링에서는
제외**한다(필요하면 `include_vctp_relay=True`로 각주(Note)만 추가로 넣을
수 있게 예약해뒀다).

방향(화살표) 추론은 CallEvent 스키마에 별도 컬럼이 없으므로, 어댑터가
보존해둔 `raw_line`(원본 블록 전체)을 이 모듈에서 다시 정규식으로
살펴봐서 판단한다 — DB 스키마를 변경하지 않고도 참가자 추론 로직을 독립적으로
개선할 수 있게 하기 위함이다 (예: vcsm의 요청/응답 근사 규칙은 TODO로
문서화된 한계가 있다. `vcsm_adapter.py` 참고).
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from app.models.call_event import CallEvent, CallEventSource

Protocol = Literal["volte", "mcptt"]

_UE = "UE"
_VCS = "VCS"
_SIPP_UE = "SIPp_UE"
_VCMC = "VCMC"
_VCMM = "VCMM"

_PARTICIPANTS: dict[Protocol, list[tuple[str, str]]] = {
    # (id, mermaid label)
    "volte": [(_UE, "UE"), (_VCS, "VCS(vctp/vcsm)"), (_VCMM, "VCMM")],
    "mcptt": [(_SIPP_UE, "SIPp/UE"), (_VCMC, "VCMC"), (_VCMM, "VCMM")],
}

_IS_SENDER_RE = re.compile(r'isSender="(?P<val>true|false)"')
_MSG_FROM_RE = re.compile(r'"msgFrom":\s*"(?P<val>[^"]+)"')
_MESSAGE_ACTION_RE = re.compile(r"message\s+(?P<action>receive|send)\s+ok\.")


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
    없다. SIP 요청(Request-Line)은 UE->VCS, 응답(Status-Line)은 VCS->UE로
    근사한다. 실패/에러 케이스 로그로 재검증 전까지는 근사치임을 유지한다.
    """
    if event.reason_code is not None:  # 응답(상태코드)
        return _VCS, _UE
    return _UE, _VCS


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
    peer = _VCS if protocol == "volte" else _VCMC
    if action_m.group("action") == "receive":
        return peer, _VCMM
    return _VCMM, peer


def _event_label(event: CallEvent) -> str:
    return _sanitize_label(event.parsed_type)


def generate_mermaid(
    events: Sequence[CallEvent],
    protocol: Protocol | None = None,
    include_vctp_relay: bool = False,
) -> str:
    """`CallEvent` 시퀀스를 Mermaid `sequenceDiagram` 텍스트로 변환한다.

    `events`는 이미 시간순으로 정렬되어 있다고 가정한다
    (`app.services.log_parser.base.assign_sequence` 참고). 이 함수 자체는
    안전을 위해 `seq_no` 기준으로 재정렬한다.
    """
    proto = protocol or detect_protocol(events)
    ordered = sorted(events, key=lambda e: e.seq_no)

    lines: list[str] = ["sequenceDiagram"]
    for pid, label in _PARTICIPANTS[proto]:
        lines.append(f"    participant {pid} as {label}")

    for event in ordered:
        if event.source == CallEventSource.VCTP_LOG:
            if include_vctp_relay:
                lines.append(f"    Note over {_VCS}: (vctp relay) {_event_label(event)}")
            continue

        if not event.parsed_type.startswith("SIP_") and event.source in (
            CallEventSource.VCSM_LOG,
            CallEventSource.VCMC_LOG,
        ):
            # SIP 이벤트가 아닌 참고성 이벤트(예: vcsm의 DURATION_CALCULATED)는
            # 화살표 대신 각주(Note)로만 표시한다.
            lane = _VCS if event.source == CallEventSource.VCSM_LOG else _VCMC
            lines.append(f"    Note over {lane}: {_event_label(event)}")
            continue

        edge: tuple[str, str] | None
        if event.source in (CallEventSource.VCSM_LOG,):
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

    return "\n".join(lines) + "\n"
