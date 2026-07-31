"""로그 파싱 공통 기반 (CLAUDE.md §9, §9.1).

실제 로그 샘플(`docs/log_samples/`)에서 확인된 공통 라인 그래머는 다음과
같다::

    [YYYY-MM-DD HH:MM:SS.mmm][LEVEL] [Thread-Name] (callId) (from) (to) 메시지 - (ClassName.java:lineNo)

`callId`/`from`/`to` 3개 괄호 그룹은 문맥에 따라 아예 없을 수도 있다(예:
`vctp.log`의 부팅 배너, 일부 내부 로그 라인). 또한 일부 메시지는 본문에
SIP 메시지 원문 전체(vcsm/vcmc) 또는 JSON(vcmm의 RMQ 메시지)을 포함하는
"블록"(멀티라인)이며, 트레일러(` - (ClassName.java:lineNo)`)가 첫 줄이
아니라 블록의 마지막 줄에만 등장한다.

이 모듈은 프로세스에 무관한 두 단계의 결정론적 파서를 제공한다:

1. `iter_log_lines()`: 원본 라인 스트림 -> `LogLine`(헤더 필드 + 블록 전체
   본문 + 트레일러 파일/라인) 스트림. 라인 단위든 블록 단위든 이 함수를
   거치면 항상 `LogLine` 하나로 정규화된다.
2. 각 `LogAdapter` 구현체(`VctpLogAdapter` 등)가 `LogLine.body`의 내용을
   프로세스별 정규식으로 다시 파싱해 `ParsedEvent`(0개 이상)를 만든다.

`LogAdapter.parse()`는 원본 로그 전체를 한 번에 문자열로 읽지 않고, 라인
제너레이터를 그대로 흘려보낸다 (token-guardian-agent 원칙: 파일은
`open(path)`로 스트리밍해서 넘긴다. `docs/log_samples/log_parser` 테스트
fixture도 이 방식을 따른다).
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.models.call_event import CallEvent, CallEventSource

# ---------------------------------------------------------------------------
# 1단계: 공통 라인 그래머 -> LogLine
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(
    r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]\[(?P<level>\w+)\s*\]\s*"
    r"\[(?P<thread>[^\]]+)\]\s*"
    r"(?:\((?P<call_id>[^)]*)\)\s*\((?P<from_no>[^)]*)\)\s*\((?P<to_no>[^)]*)\)\s*)?"
    r"(?P<rest>.*)$"
)

# 블록/단일 라인 공통 트레일러: 라인의 끝이 " - (ClassName.java:lineNo)" 형태.
# 블록 중간 본문(SDP/JSON/XML)에는 이 형태가 등장하지 않는다는 것을 실제
# 샘플 5개 파일에서 확인했다 (CLAUDE.md §9.1).
_TRAILER_SUFFIX_RE = re.compile(r"^(?P<pre>.*?)-\s*\((?P<class_file>[\w.]+\.java):(?P<line_no>\d+)\)\s*$")


def _parse_ts(ts_str: str) -> datetime:
    return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")


@dataclass(frozen=True)
class LogLine:
    """공통 그래머로 정규화된 한 개의 로그 엔트리(라인 또는 블록)."""

    ts: datetime
    level: str
    thread: str
    call_id: str | None
    from_no: str | None
    to_no: str | None
    body: str  # 헤더 이후 실제 메시지 본문 (여러 줄이면 "\n"으로 결합)
    class_file: str
    line_no: int
    raw: str  # 원본 텍스트 전체 (헤더 라인부터 트레일러 라인까지, "\n" 결합)

    @property
    def body_first_line(self) -> str:
        return self.body.split("\n", 1)[0]


def iter_log_lines(lines: Iterable[str]) -> Iterator[LogLine]:
    """원본 라인 스트림을 `LogLine` 스트림으로 정규화한다.

    상태머신 규칙: 헤더 라인(`_HEADER_RE`)의 `rest`가 이미 트레일러로
    끝나면 단일 라인 이벤트. 그렇지 않으면 트레일러로 끝나는 라인을 만날
    때까지 이어지는 raw 라인들을 그대로 본문에 누적한다(블록 모드).
    헤더 패턴에 매치하지 않는 라인(부팅 배너 등 그래머를 벗어난 라인)은
    블록 모드가 아닐 때는 무시한다.
    """
    header: dict[str, str] | None = None
    body_parts: list[str] = []
    raw_parts: list[str] = []

    for raw in lines:
        line = raw.rstrip("\r\n")

        if header is None:
            m = _HEADER_RE.match(line)
            if not m:
                continue  # 그래머를 벗어난 라인은 건너뜀 (예: 시작 배너)
            rest = m.group("rest")
            trailer_m = _TRAILER_SUFFIX_RE.match(rest)
            if trailer_m:
                pre = trailer_m.group("pre").rstrip()
                yield LogLine(
                    ts=_parse_ts(m.group("ts")),
                    level=m.group("level").strip(),
                    thread=m.group("thread"),
                    call_id=m.group("call_id") or None,
                    from_no=m.group("from_no") or None,
                    to_no=m.group("to_no") or None,
                    body=pre,
                    class_file=trailer_m.group("class_file"),
                    line_no=int(trailer_m.group("line_no")),
                    raw=line,
                )
                continue
            # 블록 시작: 트레일러 없이 계속된다.
            header = m.groupdict()
            body_parts = [rest] if rest else []
            raw_parts = [line]
        else:
            trailer_m = _TRAILER_SUFFIX_RE.match(line)
            if trailer_m:
                pre = trailer_m.group("pre").rstrip()
                if pre:
                    body_parts.append(pre)
                raw_parts.append(line)
                yield LogLine(
                    ts=_parse_ts(header["ts"]),
                    level=header["level"].strip(),
                    thread=header["thread"],
                    call_id=header["call_id"] or None,
                    from_no=header["from_no"] or None,
                    to_no=header["to_no"] or None,
                    body="\n".join(body_parts),
                    class_file=trailer_m.group("class_file"),
                    line_no=int(trailer_m.group("line_no")),
                    raw="\n".join(raw_parts),
                )
                header = None
                body_parts = []
                raw_parts = []
            else:
                body_parts.append(line)
                raw_parts.append(line)

    # 파일이 블록 도중 잘린 경우(수집 중 tail 등) 미완성 블록은 조용히 버린다.
    # TODO: 실시간 tail 연동 시 "블록 미완성" 상태를 log_collector와 어떻게
    # 넘길지는 아직 미확정 (§13 TBD와 별개로, 이 에이전트 범위에서 추가 확인 필요).


# ---------------------------------------------------------------------------
# 2단계: LogLine -> ParsedEvent (프로세스별 어댑터가 구현)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedEvent:
    """어댑터가 만든, DB 저장 전 단계의 이벤트 초안."""

    ts: datetime
    parsed_type: str
    raw_line: str
    call_id: str | None = None
    reason_code: int | None = None
    extra: dict[str, object] = field(default_factory=dict)


class LogAdapter(ABC):
    """원본 로그(라인/블록) -> `ParsedEvent` 후보 리스트 변환 인터페이스.

    CLAUDE.md §9: 파싱은 항상 결정론적 코드(정규식/상태머신)로 수행한다.
    """

    source: ClassVar[CallEventSource]

    def parse(self, lines: Iterable[str]) -> Iterator[ParsedEvent]:
        """원본 라인 스트림에서 이 어댑터가 인식하는 이벤트만 생성한다.

        인식하지 못하는 `LogLine`은 조용히 건너뛴다(노이즈 필터링).
        """
        for log_line in iter_log_lines(lines):
            event = self.match(log_line)
            if event is not None:
                yield event

    @abstractmethod
    def match(self, log_line: LogLine) -> ParsedEvent | None:
        """정규화된 `LogLine` 하나를 이 어댑터가 다루는 이벤트로 변환.

        해당 어댑터가 관심 없는 라인이면 None을 반환한다(필터링).
        """
        raise NotImplementedError


def build_call_events(
    run_id: str,
    source: CallEventSource,
    parsed_events: Iterable[ParsedEvent],
    start_seq: int = 0,
) -> list[CallEvent]:
    """`ParsedEvent` 목록을 실제 `CallEvent` ORM 인스턴스로 물질화한다."""
    events: list[CallEvent] = []
    for i, pe in enumerate(parsed_events, start=start_seq):
        events.append(
            CallEvent(
                run_id=run_id,
                ts=pe.ts,
                source=source,
                raw_line=pe.raw_line,
                parsed_type=pe.parsed_type,
                call_id=pe.call_id,
                reason_code=pe.reason_code,
                seq_no=i,
            )
        )
    return events


def parse_lines_with_adapter(
    adapter: LogAdapter, lines: Iterable[str], run_id: str, start_seq: int = 0
) -> list[CallEvent]:
    """어댑터 1개로 라인 스트림을 바로 `CallEvent` 리스트로 변환하는 헬퍼."""
    return build_call_events(run_id, adapter.source, adapter.parse(lines), start_seq=start_seq)


def assign_sequence(events: list[CallEvent]) -> list[CallEvent]:
    """여러 소스(vctp/vcsm/vcmm/vcmc/sipp)에서 온 이벤트를 시간순으로 병합하고
    `seq_no`를 새로 부여한다.

    McPTT는 VCS 로그와 SIPp 로그를 Call-ID/타임스탬프 기준으로 상관관계
    매칭해서 하나의 Call Flow로 합친다 (CLAUDE.md §3.2). 이 함수가 그 병합의
    마지막 단계(정렬 + 재번호)를 담당한다. 매칭/상관관계 로직 자체(예: SIPp
    로그의 Call-ID 형식 확정)는 `sipp_adapter.py`의 TODO로 남겨둔다.
    """
    ordered = sorted(events, key=lambda e: (e.ts, e.seq_no))
    for i, event in enumerate(ordered):
        event.seq_no = i
    return ordered


def read_file_lines(path: str) -> Iterator[str]:
    """대용량 로그 파일을 한 번에 메모리에 올리지 않고 라인 단위로 스트리밍한다.

    (token-guardian-agent 원칙: 파일 전체를 문자열 하나로 읽지 않는다.)
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        yield from f
