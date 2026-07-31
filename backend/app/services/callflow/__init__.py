"""Call Flow(Mermaid) 생성 + Pass/Fail 판정 규칙 엔진 패키지 (CLAUDE.md §9).

다른 에이전트 사용법::

    from app.services.callflow import generate_mermaid, evaluate_pass_fail, PassFailResult

    mermaid_source = generate_mermaid(events)  # protocol은 events의 source로 자동 판별
    result = evaluate_pass_fail(events, test_case.pass_criteria)
"""
from app.services.callflow.generator import detect_protocol, generate_mermaid  # noqa: F401
from app.services.callflow.rules import PassFailResult, evaluate_pass_fail  # noqa: F401

__all__ = [
    "PassFailResult",
    "detect_protocol",
    "evaluate_pass_fail",
    "generate_mermaid",
]
