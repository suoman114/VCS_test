"""`vcmm.log` 어댑터 (VoLTE·McPTT 공통 녹취 제어 메시지, CLAUDE.md §9.1).

VoLTE(`docs/log_samples/volte/vcmm.log`)와 McPTT
(`docs/log_samples/mcptt/vcmm.log`) 양쪽 모두 동일한 포맷을 사용하므로
어댑터 하나를 공유한다.

확인된 블록 패턴::

    [ts][INFO ] [thread] (callId) () () -> recording_start_req message receive ok. [{
      "header": { "type": "recording_start_req", "callId": "...", "transactionId": "...",
                  "msgFrom": "VCSM", "trxType": 1, "reasonCode": 0 },
      "body": { ... }
    }] - (RmqConsumer.java:86)

    [ts][INFO ] [thread] (callId) () () -> VCSM recording_start_res message send ok. [{
      "header": { ..., "reasonCode": 2000, "reason": "Success" },
      "body": { ... }
    }] - (OutgoingMessage.java:82)

메시지 타입 4종(관측됨): `recording_start_req/res`, `recording_stop_req/res`.
McPTT에서는 추가로 `recording_change_req/res`(그룹 발언권/플로어 변경 추정,
샘플에서 21회 관측)도 동일 포맷으로 등장한다.

**Pass 판정 1차 근거** (CLAUDE.md §9.1, §13):
`recording_stop_res`의 `header.reasonCode == 2000 && header.reason ==
"Success"`. 이 어댑터는 `reason_code`를 `CallEvent.reason_code` 컬럼에
그대로 채우고, `reason` 문자열은 `raw_line`(원본 JSON 블록)에 보존해
`app.services.callflow.rules`가 재파싱해서 쓸 수 있게 한다.

TODO(§13 미확인): 실패/타임아웃 케이스 로그가 없어 reasonCode!=2000일 때의
전체 스펙트럼(에러 코드 종류)은 확인하지 못했다. `recording_change_*`의
정확한 의미/Pass 판정 영향 여부도 미확인이다.
"""
from __future__ import annotations

import json
import re

from app.models.call_event import CallEventSource
from app.services.log_parser.base import LogAdapter, LogLine, ParsedEvent

_OPEN_RE = re.compile(
    r"^->\s*(?:(?P<peer>[A-Za-z0-9_]+)\s+)?"
    r"(?P<msg_type>recording_(?:start|stop|change)_(?:req|res))\s+"
    r"message\s+(?P<direction>receive|send)\s+ok\.\s*\[(?P<json>.*)\]$",
    re.DOTALL,
)


class VcmmLogAdapter(LogAdapter):
    """`vcmm.log` -> 녹취 제어(RMQ JSON) 이벤트."""

    source = CallEventSource.VCMM_LOG

    def match(self, log_line: LogLine) -> ParsedEvent | None:
        m = _OPEN_RE.match(log_line.body)
        if not m:
            return None

        try:
            payload = json.loads(m.group("json"))
        except json.JSONDecodeError:
            # 결정론적 파서 원칙: JSON이 깨져 있으면 추측하지 않고 건너뛴다.
            return None

        header = payload.get("header", {}) if isinstance(payload, dict) else {}
        msg_type = header.get("type", m.group("msg_type"))
        call_id = header.get("callId") or log_line.call_id
        reason_code = header.get("reasonCode")
        if isinstance(reason_code, str) and reason_code.isdigit():
            reason_code = int(reason_code)
        elif not isinstance(reason_code, int):
            reason_code = None

        return ParsedEvent(
            ts=log_line.ts,
            parsed_type=msg_type.upper(),
            raw_line=log_line.raw,
            call_id=call_id,
            reason_code=reason_code,
            extra={
                "direction": m.group("direction"),
                "peer": m.group("peer"),
                "msg_from": header.get("msgFrom"),
                "reason": header.get("reason"),
            },
        )
