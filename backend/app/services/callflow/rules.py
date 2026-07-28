"""Pass/Fail 판정 규칙 엔진 (CLAUDE.md §6 `pass_criteria`, §9, §13).

확인된 성공 판정 근거(CLAUDE.md §9.1, §13 — VoLTE/McPTT 각 1건의 성공
샘플에서 확인):

    recording_stop_res.header.reasonCode == 2000
    and recording_stop_res.header.reason == "Success"

**TODO(§13 미확인)**: 실패/타임아웃 케이스의 실제 로그가 아직 없어 Fail
쪽 패턴(에러 코드 종류, SIP 4xx/5xx가 실제로 실패를 의미하는지, 타임아웃
시 어떤 로그가 남는지)은 확정할 수 없다. 이 모듈은 "성공 조건을 만족하지
못하면 fail 후보로 본다"는 방어적 기본값만 제공하고, 실제 실패 로그가
확보되면 `forbidden_patterns` 등을 강화해야 한다.

`TestCase.pass_criteria`(JSON/dict, testcase-manager-agent 스키마 주석
기준)와 비교하는 확장 가능한 구조:

    {
        "require_recording_success": true,       # 기본값 True
        "required_events": ["SIP_INVITE", "SIP_200", ...],  # parsed_type 존재 검사
        "forbidden_patterns": ["SIP_4\\d\\d", "SIP_5\\d\\d"],  # parsed_type/raw_line 정규식
        "max_duration_sec": 30
    }

모든 키는 선택적이며, `pass_criteria`가 비어있거나 None이면 기본 규칙
(recording_stop_res 성공 여부)만 적용한다.
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.models.call_event import CallEvent, CallEventSource

_RECORDING_STOP_RES = "RECORDING_STOP_RES"

# vcmm.log 이벤트의 raw_line은 원본 블록 전체(헤더 라인 + JSON + 트레일러
# " - (Class.java:line)")를 그대로 보존한다. `[{ ... }]` 안의 JSON 객체만
# 다시 뽑아낸다(양쪽 대괄호 사이 첫 "{"~마지막 "}" 전체를 그리디로 포착 —
# 현재 샘플의 JSON body에는 배열(`[]`)이 없어 안전하다는 것을 확인했다).
_JSON_BLOCK_RE = re.compile(r"\[(?P<json>\{.*\})\]", re.DOTALL)


@dataclass
class PassFailResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def _extract_vcmm_header(event: CallEvent) -> dict[str, Any] | None:
    """vcmm.log 이벤트의 raw_line(원본 JSON 블록)에서 header dict를 재추출한다.

    CallEvent 스키마에는 `reason`(문자열) 컬럼이 없어(§6, reason_code만
    존재) raw_line을 다시 정규식+json으로 파싱한다.
    """
    if event.source != CallEventSource.VCMM_LOG:
        return None
    m = _JSON_BLOCK_RE.search(event.raw_line)
    if not m:
        return None
    try:
        payload = json.loads(m.group("json"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    header = payload.get("header")
    return header if isinstance(header, dict) else None


def _check_recording_success(events: Sequence[CallEvent]) -> tuple[bool, str]:
    stop_res_events = [e for e in events if e.parsed_type == _RECORDING_STOP_RES]
    if not stop_res_events:
        return False, "recording_stop_res 이벤트를 찾지 못함 (vcmm.log 미확인 또는 호 미종료)"

    for event in stop_res_events:
        header = _extract_vcmm_header(event)
        reason_code = header.get("reasonCode") if header else event.reason_code
        reason = header.get("reason") if header else None
        if reason_code == 2000 and reason == "Success":
            return True, f"recording_stop_res reasonCode=2000 reason=Success (call_id={event.call_id})"

    codes = [(e.call_id, e.reason_code) for e in stop_res_events]
    return False, f"recording_stop_res success 조건 미충족: {codes}"


def _check_required_events(events: Sequence[CallEvent], required: list[str]) -> list[str]:
    present = {e.parsed_type for e in events}
    return [req for req in required if req not in present]


def _check_forbidden_patterns(events: Sequence[CallEvent], patterns: list[str]) -> list[str]:
    hits: list[str] = []
    compiled = [re.compile(p) for p in patterns]
    for event in events:
        for pattern in compiled:
            if pattern.search(event.parsed_type) or pattern.search(event.raw_line):
                hits.append(f"{pattern.pattern} matched parsed_type={event.parsed_type} call_id={event.call_id}")
    return hits


def _check_max_duration(events: Sequence[CallEvent], max_duration_sec: float) -> str | None:
    duration_events = [e for e in events if e.parsed_type == "DURATION_CALCULATED"]
    if not duration_events:
        return None
    m = re.search(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})", duration_events[0].raw_line)
    if not m:
        return None
    h, mi, s, ms = (int(x) for x in m.groups())
    total_sec = h * 3600 + mi * 60 + s + ms / 1000
    if total_sec > max_duration_sec:
        return f"Duration {total_sec:.3f}s exceeds max_duration_sec={max_duration_sec}"
    return None


def evaluate_pass_fail(
    events: Sequence[CallEvent], pass_criteria: dict[str, Any] | None = None
) -> PassFailResult:
    """파싱된 `CallEvent` 시퀀스와 `TestCase.pass_criteria`를 비교해 판정한다."""
    criteria = pass_criteria or {}
    reasons: list[str] = []
    passed = True
    details: dict[str, Any] = {}

    if criteria.get("require_recording_success", True):
        ok, reason = _check_recording_success(events)
        details["recording_success"] = ok
        reasons.append(reason)
        passed = passed and ok

    required_events = criteria.get("required_events") or []
    if required_events:
        missing = _check_required_events(events, required_events)
        details["missing_required_events"] = missing
        if missing:
            passed = False
            reasons.append(f"필수 이벤트 누락: {missing}")

    forbidden_patterns = criteria.get("forbidden_patterns") or []
    if forbidden_patterns:
        hits = _check_forbidden_patterns(events, forbidden_patterns)
        details["forbidden_pattern_hits"] = hits
        if hits:
            passed = False
            reasons.append(f"금지 패턴 발견: {hits}")

    max_duration_sec = criteria.get("max_duration_sec")
    if max_duration_sec is not None:
        duration_reason = _check_max_duration(events, max_duration_sec)
        if duration_reason:
            passed = False
            reasons.append(duration_reason)

    return PassFailResult(passed=passed, reasons=reasons, details=details)
