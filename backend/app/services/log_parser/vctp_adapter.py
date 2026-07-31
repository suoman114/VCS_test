"""`vctp.log` 어댑터 (CLAUDE.md §9.1).

실제 샘플(8972줄) 분석 결과 99%(8866줄)가 `DumpPacketTask.java:156`
("send RTP message to VCMM")류의 패킷 단위 RTP relay 로그로 Call Flow
관점에서는 노이즈다. 이 어댑터는 그 라인들을 기본적으로 필터링하고,
`DumpPacketTask.java:131`("send SIP message to VCSM", SIP 메서드/상태
포함)만 저비중 참고용으로 채택한다.

SIP 시그널링의 1차 소스는 `VcsmLogAdapter`/`VcmcLogAdapter`이다. 이
어댑터가 만드는 이벤트는 vctp가 실제로 SIP 메시지를 VCSM으로 릴레이했다는
사실을 보조적으로 확인하는 용도이며, Call Flow 기본 렌더링에서는 제외한다
(`app.services.callflow.generator` 참고).

확인된 패턴 (vctp.log 57번째 줄 등)::

    [ts][INFO ] [Thread-5] send SIP message to VCSM. 10.64.0.54:5060 length=2138 mapSize=0 message=INVITE tel:... SIP/2.0 - (DumpPacketTask.java:131)

주의: 이 라인에는 callId/from/to 트리플 괄호가 없고(vctp 프로세스는 SIP
헤더를 파싱하지 않고 첫 줄만 릴레이 로그에 남긴다), `message=` 뒤에는 SIP
요청/응답의 첫 줄만 포함된다(Call-ID 등 전체 헤더는 없음). 따라서 이
어댑터가 만드는 CallEvent의 `call_id`는 항상 None이다 (TODO: 필요하면
같은 스레드/시간대의 vcsm 이벤트와 매칭해 call_id를 보강할 수 있으나,
현재는 추측하지 않는다).
"""
from __future__ import annotations

import re

from app.models.call_event import CallEventSource
from app.services.log_parser.base import LogAdapter, LogLine, ParsedEvent
from app.services.log_parser.sip_common import parse_sip_first_line

_RELAY_RE = re.compile(
    r"^send SIP message to VCSM\.\s+(?P<peer>\S+)\s+length=(?P<length>\d+)\s+"
    r"mapSize=(?P<map_size>\d+)\s+message=(?P<sip_first_line>.+)$"
)


class VctpLogAdapter(LogAdapter):
    """`vctp.log` -> 저비중 SIP relay 참고 이벤트만 추출."""

    source = CallEventSource.VCTP_LOG

    def match(self, log_line: LogLine) -> ParsedEvent | None:
        if log_line.class_file != "DumpPacketTask.java" or log_line.line_no != 131:
            return None  # DumpPacketTask.java:156(RTP relay 노이즈) 등은 전부 제외

        m = _RELAY_RE.match(log_line.body_first_line)
        if not m:
            return None

        parsed = parse_sip_first_line(m.group("sip_first_line"))
        if parsed is None:
            return None
        method_or_code, reason_code = parsed

        return ParsedEvent(
            ts=log_line.ts,
            parsed_type=f"VCTP_RELAY_SIP_{method_or_code}",
            raw_line=log_line.raw,
            call_id=None,
            reason_code=reason_code,
            extra={"peer": m.group("peer")},
        )
