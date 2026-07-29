"""TestRun / CallEvent / CallFlowDiagram Pydantic 스키마 (API 경계 검증).

CLAUDE.md §6 데이터 모델을 그대로 따른다. TestRun 상태값 의미는
`app.models.test_run.TestRunStatus` 문서화 참고(DONE=Pass, FAILED=Fail,
ERROR=인프라 실패).

다른 에이전트 사용법:
    from app.schemas.test_run import TestRunRead, TestRunListResponse, CallEventRead, CallEventListResponse, CallFlowRead
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

TestRunStatusLiteral = Literal["pending", "running", "parsing", "done", "failed", "error"]
CallEventSourceLiteral = Literal["vctp_log", "vcsm_log", "vcmm_log", "vcmc_log", "sipp_log"]


class TestRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    test_case_id: str
    status: TestRunStatusLiteral
    started_at: datetime | None
    ended_at: datetime | None
    target_host: str | None
    raw_log_path: str | None
    result_summary: str | None
    created_at: datetime
    updated_at: datetime


class TestRunListResponse(BaseModel):
    items: list[TestRunRead]
    total: int


class CallEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    ts: datetime
    source: CallEventSourceLiteral
    raw_line: str
    parsed_type: str
    call_id: str | None
    reason_code: int | None
    seq_no: int


class CallEventListResponse(BaseModel):
    items: list[CallEventRead]
    total: int


class CallFlowMessageRead(BaseModel):
    """Call Flow의 메시지(화살표) 하나 -> 원본 CallEvent 참조 (클릭-투-로그용).

    `index`는 렌더된 Mermaid `.messageText` 엘리먼트 순서와 1:1 대응한다
    (`app.services.callflow.generator.CallFlowMessageRef` 참고).
    """

    index: int
    seq_no: int
    source: CallEventSourceLiteral
    call_id: str | None


class CallFlowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    mermaid_source: str
    generated_at: datetime
    messages: list[CallFlowMessageRead] = []
