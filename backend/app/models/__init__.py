"""SQLAlchemy 모델 패키지.

Alembic autogenerate가 전체 스키마를 인식할 수 있도록 여기서 모든 모델
모듈을 import한다. 다른 에이전트가 새 모델(TestCase, CallEvent,
CallFlowDiagram 등)을 추가하면 이 파일에도 import를 추가해야 한다.
"""
from app.models.call_event import CallEvent, CallEventSource  # noqa: F401
from app.models.call_flow import CallFlowDiagram  # noqa: F401
from app.models.test_case import TestCase, TestCaseCategory, TestCaseType  # noqa: F401
from app.models.test_run import TestRun, TestRunStatus  # noqa: F401

__all__ = [
    "CallEvent",
    "CallEventSource",
    "CallFlowDiagram",
    "TestCase",
    "TestCaseCategory",
    "TestCaseType",
    "TestRun",
    "TestRunStatus",
]
