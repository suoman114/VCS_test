"""`vcsm.log` 어댑터 (VoLTE SIP 시그널링 1차 소스, CLAUDE.md §9.1).

확인된 블록 패턴(예시, 총 14회 관측)::

    [ts][INFO ] [thread] () () () NettyUdpPacket Data INVITE MESSAGE : INVITE tel:01033330001;... SIP/2.0
    From: <sip:...>
    To: <tel:...>
    Call-ID: B4BAC090637B72924847837C@10.64.0.54
    ...
    Content-Length: 906
    <blank>
    v=0
    ... (SDP)
     - (RecordHandler.java:132)

`iter_log_lines()`가 위 블록 전체를 `LogLine.body`로 재구성해준다
(첫 줄 "NettyUdpPacket Data <TAG> MESSAGE : <SIP 첫줄>" + 이어지는 SIP
헤더/SDP 원문, 트레일러 라인은 " - (RecordHandler.java:132)"처럼 블록
마지막에만 등장).

같은 파일에는 `[RMQ MESSAGE] Json --> {...}` / `[RMQ MESSAGE] onReceived :
{...}` 블록(녹취 제어 JSON)도 존재하지만, 이는 `vcmm.log`에 있는 동일
이벤트(recording_start_req/res 등)의 VCSM측 사본이라 **중복을 피하기
위해 이 어댑터에서는 무시**하고 `VcmmLogAdapter`를 1차 소스로 삼는다
(CLAUDE.md §9.1).

`Duration calculated: HH:MM:SS.mmm` 단일 라인(`RecordCompleteHandler.java:
40`)도 이 어댑터가 `DURATION_CALCULATED` 이벤트로 추출한다(통화 지속시간
참고용, call_id는 이 라인에 없어 None).

TODO(방향성 근사): vcsm 블록 헤더에는 vcmc의 `isSender`처럼 송수신 방향을
명시하는 필드가 없다. Call Flow 생성 단계(`app.services.callflow`)에서는
"요청(Request-Line)=UE→VCS 착신 관점" / "응답(Status-Line)=VCS→UE"라는
근사 규칙을 쓴다 — 실제 B2BUA 양쪽 leg를 엄밀히 구분한 것은 아니며,
실패/에러 케이스 로그 확보 후 재검증이 필요하다.
"""
from __future__ import annotations

import re

from app.models.call_event import CallEventSource
from app.services.log_parser.base import LogAdapter, LogLine, ParsedEvent
from app.services.log_parser.sip_common import extract_sip_header, parse_sip_first_line

_NETTY_RE = re.compile(r"^NettyUdpPacket Data \S+ MESSAGE\s*:\s*(?P<sip_first_line>.+)$")
_DURATION_RE = re.compile(r"^Duration calculated:\s*(?P<duration>\d{2}:\d{2}:\d{2}\.\d{3})$")


class VcsmLogAdapter(LogAdapter):
    """`vcsm.log` -> SIP 시그널링 이벤트(+ Duration 참고 이벤트)."""

    source = CallEventSource.VCSM_LOG

    def match(self, log_line: LogLine) -> ParsedEvent | None:
        netty_m = _NETTY_RE.match(log_line.body_first_line)
        if netty_m:
            return self._match_sip_block(log_line, netty_m.group("sip_first_line"))

        duration_m = _DURATION_RE.match(log_line.body)
        if duration_m:
            return ParsedEvent(
                ts=log_line.ts,
                parsed_type="DURATION_CALCULATED",
                raw_line=log_line.raw,
                call_id=log_line.call_id,
                reason_code=None,
                extra={"duration": duration_m.group("duration")},
            )

        return None  # [RMQ MESSAGE] 블록 등은 의도적으로 무시 (vcmm.log가 1차 소스)

    def _match_sip_block(self, log_line: LogLine, sip_first_line: str) -> ParsedEvent | None:
        parsed = parse_sip_first_line(sip_first_line)
        if parsed is None:
            return None
        method_or_code, reason_code = parsed

        call_id = extract_sip_header(log_line.body, "Call-ID") or log_line.call_id

        return ParsedEvent(
            ts=log_line.ts,
            parsed_type=f"SIP_{method_or_code}",
            raw_line=log_line.raw,
            call_id=call_id,
            reason_code=reason_code,
        )
