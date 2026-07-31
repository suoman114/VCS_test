"""TestCase Pydantic 스키마 (API 경계 검증).

`category`/`test_type`는 독립된 축이다 (CLAUDE.md §7). API 응답/요청에서는
`app.models.test_case.TestCaseCategory` / `TestCaseType`과 동일한 문자열
값을 사용하는 `Literal`로 검증한다 (Pydantic 스키마 계층은 SQLAlchemy
Enum 클래스에 의존하지 않고 순수 문자열로 다뤄 backend/frontend 양쪽에서
가볍게 참조할 수 있게 한다).

다른 에이전트 사용법:
    from app.schemas.test_case import TestCaseCreate, TestCaseUpdate, TestCaseRead
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TestCaseCategoryLiteral = Literal["volte", "mcptt"]
TestCaseTypeLiteral = Literal["basic_call", "performance", "abnormal"]


class TestCaseBase(BaseModel):
    """생성/수정 요청의 공통 필드."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    category: TestCaseCategoryLiteral
    test_type: TestCaseTypeLiteral = "basic_call"

    # VoLTE: vctp 설정 파일 경로. McPTT: 메인 SIPp 시나리오(XML) 경로.
    config_ref: str = Field(..., min_length=1, max_length=512)

    # 프로토콜별 부가 파라미터. 구조 예시는 완료 보고 참고.
    protocol_params: dict[str, Any] = Field(default_factory=dict)

    # 판정 기준. 예: {"required_events": [...], "forbidden_patterns": [...], "max_duration_sec": 30}
    pass_criteria: dict[str, Any] = Field(default_factory=dict)

    # testcases/{volte,mcptt}/*.yaml 중 이 레코드와 동기화된 파일의 저장소 루트 기준 상대 경로.
    yaml_path: str | None = Field(default=None, max_length=512)


class TestCaseCreate(TestCaseBase):
    """POST /api/test-cases 요청 바디."""

    # id는 클라이언트가 지정할 수도(YAML의 id 재사용), 서버가 생성할 수도 있다.
    id: str | None = Field(default=None, max_length=36)


class TestCaseUpdate(BaseModel):
    """PATCH /api/test-cases/{id} 요청 바디. 모든 필드가 선택적(부분 갱신)이다."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: TestCaseCategoryLiteral | None = None
    test_type: TestCaseTypeLiteral | None = None
    config_ref: str | None = Field(default=None, min_length=1, max_length=512)
    protocol_params: dict[str, Any] | None = None
    pass_criteria: dict[str, Any] | None = None
    yaml_path: str | None = Field(default=None, max_length=512)


class TestCaseRead(TestCaseBase):
    """API 응답 바디."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class TestCaseListResponse(BaseModel):
    """GET /api/test-cases 목록 응답 (페이지네이션 포함)."""

    items: list[TestCaseRead]
    total: int
