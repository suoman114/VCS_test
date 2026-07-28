"""`vcmc.log` 어댑터 (McPTT SIP+MCPTT 시그널링 1차 소스, CLAUDE.md §9.1).

vcmc.log는 공통 라인 그래머의 `(callId)(from)(to)` 트리플 대신, 자체
XML풍 `<message ...>...<![CDATA[...]]></message>` 블록으로 SIP 원문을
감싼다. 확인된 패턴(2250줄 샘플에서 다수 관측)::

    [ts][INFO ] [thread] <message
    from="192.168.7.65:5080"
    to="172.10.11.198:5060"
    time="1785223420035"
    isSender="false"
    transactionId="z9hg4bkc9c8934c-fba9-4def-96c4-68294a2cbb89"
    callId="960e2eb1475c0fca01edff976528e956@192.168.7.65_1"
    firstLine="INVITE sip:+82585109100@172.10.11.198:5060 SIP/2.0"
    >
    <![CDATA[INVITE sip:+82585109100@172.10.11.198:5060 SIP/2.0
    ... (SIP 헤더 + multipart/mixed body: mcptt-info+xml, SDP)
    ]]>
    </message>
     - (CommonLoggerLog4j.java:207)

`isSender` 속성이 명시적으로 송수신 방향을 알려준다: `"true"`이면 vcmc가
그 메시지의 발신자(vcmc -> 상대), `"false"`이면 vcmc가 수신자(상대 ->
vcmc)이다. `firstLine`이 SIP 요청/응답 첫 줄이므로 CDATA 전체를 다시
파싱하지 않고 속성만으로 필요한 필드를 채울 수 있다.

MCPTT 고유 바디(멀티파트 `application/vnd.3gpp.mcptt-info+xml`)의 상세
파싱(예: mcptt-Params의 session-type/floor 제어 등)은 SIPp Scenario
Agent/McPTT 메시지 규칙이 확정된 후 추가한다 — 지금은 CallEvent 스키마에
맞는 SIP 레벨 이벤트만 만든다. TODO로 명시.
"""
from __future__ import annotations

import re

from app.models.call_event import CallEventSource
from app.services.log_parser.base import LogAdapter, LogLine, ParsedEvent
from app.services.log_parser.sip_common import parse_sip_first_line

_MESSAGE_BLOCK_RE = re.compile(
    r"^<message\s*\n(?P<attrs>.*?)\n>\s*\n<!\[CDATA\[\n(?P<content>.*?)\n\]\]>\s*\n</message>$",
    re.DOTALL,
)
_ATTR_RE = re.compile(r'(?P<key>[A-Za-z0-9_]+)="(?P<value>[^"]*)"')


class VcmcLogAdapter(LogAdapter):
    """`vcmc.log` -> SIP(+MCPTT) 시그널링 이벤트."""

    source = CallEventSource.VCMC_LOG

    def match(self, log_line: LogLine) -> ParsedEvent | None:
        if not log_line.body.startswith("<message"):
            return None

        m = _MESSAGE_BLOCK_RE.match(log_line.body)
        if not m:
            return None

        attrs = dict(_ATTR_RE.findall(m.group("attrs")))
        first_line = attrs.get("firstLine")
        if not first_line:
            return None

        parsed = parse_sip_first_line(first_line)
        if parsed is None:
            return None
        method_or_code, reason_code = parsed

        return ParsedEvent(
            ts=log_line.ts,
            parsed_type=f"SIP_{method_or_code}",
            raw_line=log_line.raw,
            call_id=attrs.get("callId"),
            reason_code=reason_code,
            extra={
                "is_sender": attrs.get("isSender"),
                "from_addr": attrs.get("from"),
                "to_addr": attrs.get("to"),
            },
        )
