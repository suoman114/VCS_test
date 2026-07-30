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
    # TestRun ORM에는 없는 파생 필드 — 엔드포인트가 TestCase와 조인해서 채운다
    # (2026-07-30 UI 개선 요청: 대시보드/이력/실행 화면에 UUID만 보이던 문제).
    # TestCase가 삭제됐거나(현재 스키마상 불가하지만 방어적으로) 조인에 실패하면 None.
    test_case_name: str | None = None
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


class CallIdListResponse(BaseModel):
    """McPTT 성능 시험처럼 한 Test Run에 콜이 여러 건 섞여 있을 때, Call Flow를
    콜 단위로 구별해서 보기 위한 call_id 목록(`GET /test-runs/{id}/call-ids`).
    처음 등장한 순서(seq_no 기준)를 그대로 유지한다 — 알파벳 정렬보다 시험
    진행 순서와 일치해서 더 직관적이다."""

    items: list[str]


class TestRunStatsBucket(BaseModel):
    """상태 개수 -> Pass율 요약. `pass_rate`는 종료된 실행(done/failed/error)
    기준이다 — 대기/실행/분석 중인 run은 아직 결과가 없으므로 분모에서 뺀다.
    종료된 실행이 하나도 없으면 `None`(계산 불가, "-"로 표시하라는 신호)."""

    total: int
    passed: int
    failed: int
    error: int
    in_progress: int
    pass_rate: float | None


class TestRunStatsResponse(BaseModel):
    """대시보드 통계 카드용 집계 (`GET /api/test-runs/stats`).

    `by_category`는 실제로 실행 기록이 있는 카테고리만 키로 담는다(예:
    McPTT를 한 번도 안 돌렸으면 "mcptt" 키 자체가 없음).
    """

    overall: TestRunStatsBucket
    by_category: dict[str, TestRunStatsBucket]
    recent: TestRunStatsBucket
    recent_days: int


class HistogramBin(BaseModel):
    range_start_ms: float
    range_end_ms: float
    count: int


class SetupTimeStats(BaseModel):
    """콜 설정(녹취 개시) 소요시간 분포 — `recording_start_req`~`res` 기준
    (2026-07-30 사용자 확인, CLAUDE.md §13). SIP INVITE~200 OK가 아니다."""

    count: int
    min_ms: float
    avg_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    histogram: list[HistogramBin]


class ConcurrencyPoint(BaseModel):
    """`offset_sec`은 이 Test Run에서 첫 콜이 시작된 시각(0) 기준 경과 초."""

    offset_sec: int
    concurrent_calls: int


class ReportStatsResponse(BaseModel):
    """리포트 전용 파생 통계(`GET /test-runs/{id}/report-stats`,
    `app.services.report_stats`). 계산 비용 때문에 라이브 폴링에는 얹지
    않는다 — 리포트 화면 진입 시 1회만 호출하는 용도. `setup_time`은 데이터가
    없으면(REQ/RES 짝을 못 찾으면) `None`이다."""

    setup_time: SetupTimeStats | None
    concurrency_series: list[ConcurrencyPoint]
    bucket_seconds: int
