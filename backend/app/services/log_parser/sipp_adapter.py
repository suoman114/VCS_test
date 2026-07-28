"""`SippLogAdapter` (TODO, 인터페이스만 예약 — CLAUDE.md §3.2, §9, §13).

McPTT 호 발생기(SIPp)가 자체적으로 남기는 로그/통계(csv, 스크린 로그 등)를
`CallEvent`로 변환하는 어댑터. **아직 실제 SIPp 로그 샘플이
`docs/log_samples/`에 도착하지 않아 파싱 규칙을 확정할 수 없다.**

현재 확인된 것: McPTT의 SIP+MCPTT 시그널링은 VCS측 `vcmc.log`
(`VcmcLogAdapter`)에서 이미 충분히 관측 가능하다(CLAUDE.md §9.1). 따라서
SIPp 로그는 VCS 로그와의 **Call-ID/타임스탬프 상관관계 교차검증**
용도로만 필요할 가능성이 높다 (CLAUDE.md §3.2) — 예: SIPp가 실제로 보낸
타이밍과 VCS가 수신한 타이밍의 차이, SIPp 자체 실패 판정(예: 특정 시나리오
스텝 타임아웃) 등.

TODO(SIPp Scenario Agent와 조율 필요):
    - SIPp 실행 위치(로컬 vs 원격) 확정 후 로그 경로/포맷 확인
    - SIPp 스크린 로그(`-trace_msg` 등) 또는 csv 통계(`-trace_stat`) 중
      어떤 것을 1차 소스로 삼을지
    - Call-ID 상관관계 매칭 키(단순 `Call-ID` 문자열 동일 비교로 충분한지,
      아니면 SIPp가 별도 태그를 남기는지)

실제 샘플이 도착하기 전까지는 `match()`가 항상 빈 이터레이터를 반환하는
스텁으로 둔다 — 추측으로 정규식을 채우지 않는다 (CLAUDE.md §9).
"""
from __future__ import annotations

from app.models.call_event import CallEventSource
from app.services.log_parser.base import LogAdapter, LogLine, ParsedEvent


class SippLogAdapter(LogAdapter):
    """SIPp 로그 어댑터 스텁. 실제 로그 샘플 확보 후 구현한다."""

    source = CallEventSource.SIPP_LOG

    def match(self, log_line: LogLine) -> ParsedEvent | None:
        return None
