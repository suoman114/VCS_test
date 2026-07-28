"""SIP 메시지 첫 줄/헤더 파싱 공통 유틸 (vctp/vcsm/vcmc 어댑터 공용).

CLAUDE.md §9.1에서 확인된 SIP 메서드 집합: INVITE/ACK/BYE/CANCEL/UPDATE/
PRACK/NOTIFY/REFER/OPTIONS/MESSAGE. 다만 파서는 이 목록에 없는 대문자
메서드가 와도 그대로 통과시킨다(향후 스펙 확장에 결정론적으로 대응하기
위함이며, 목록에 하드코딩된 화이트리스트로 실패시키지 않는다).
"""
from __future__ import annotations

import re

_REQUEST_RE = re.compile(r"^(?P<method>[A-Z][A-Z0-9]*) \S+ SIP/2\.0\s*$")
_RESPONSE_RE = re.compile(r"^SIP/2\.0 (?P<code>\d{3})(?: .*)?$")


def parse_sip_first_line(text: str) -> tuple[str, int | None] | None:
    """SIP 요청/응답 첫 줄을 `(parsed_type_suffix, status_code)`로 변환한다.

    - 요청(`INVITE tel:... SIP/2.0`) -> `("INVITE", None)`
    - 응답(`SIP/2.0 200 OK`) -> `("200", 200)`
    - 인식 불가 -> `None`
    """
    text = text.strip()
    m = _RESPONSE_RE.match(text)
    if m:
        code = int(m.group("code"))
        return str(code), code
    m = _REQUEST_RE.match(text)
    if m:
        return m.group("method"), None
    return None


_HEADER_LINE_RE_CACHE: dict[str, re.Pattern[str]] = {}


def extract_sip_header(body: str, header_name: str) -> str | None:
    """멀티라인 SIP 메시지 본문에서 특정 헤더 값을 추출한다 (첫 매치만)."""
    pattern = _HEADER_LINE_RE_CACHE.get(header_name)
    if pattern is None:
        pattern = re.compile(rf"^{re.escape(header_name)}:\s*(?P<value>.+?)\s*$", re.MULTILINE | re.IGNORECASE)
        _HEADER_LINE_RE_CACHE[header_name] = pattern
    m = pattern.search(body)
    if m:
        return m.group("value").strip()
    return None
