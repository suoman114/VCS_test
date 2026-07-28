"""TestCase 모델 (CLAUDE.md §6, §7).

`category`(volte|mcptt)와 `test_type`(basic_call|performance|abnormal)은
독립된 축이다 (§7). 실행기는 `(category, test_type)` 조합으로 조회하며
(`app.services.executor_base.executor_registry` 참고), 이 모델은 해당
Executor들이 기대하는 `TestCaseLike` Protocol(id/category/test_type
문자열 속성)을 만족해야 한다.

프로토콜별 부가 정보(예: VoLTE의 VCS 목적지 경로/재기동 명령, McPTT의
SIPp 대상 IP/호 발생률 등)는 `config_ref`(대표 경로 1개) +
`protocol_params`(JSON, 프로토콜별 자유 구조)로 분리한다. 이렇게 하면
성능/Abnormal 시험이 추가돼도 컬럼을 늘리지 않고 protocol_params 안에서
확장할 수 있다.

NOTE(backend-agent 공유 필요): `TestRun.test_case_id`는 다음 웨이브에서
이 테이블(`test_cases`)의 `id` 컬럼(String(36))을 참조하는
`ForeignKey("test_cases.id")`로 교체될 예정이다.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Enum as SAEnum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid4_str() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TestCaseCategory(str, enum.Enum):
    """프로토콜 축 (CLAUDE.md §7). Phase 2+에서 새 프로토콜이 추가될 수 있다."""

    VOLTE = "volte"
    MCPTT = "mcptt"


class TestCaseType(str, enum.Enum):
    """시험 유형 축 (CLAUDE.md §7). Phase 1은 BASIC_CALL만 사용한다."""

    BASIC_CALL = "basic_call"
    PERFORMANCE = "performance"
    ABNORMAL = "abnormal"


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4_str)

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 프로토콜 축: "volte" | "mcptt"
    category: Mapped[TestCaseCategory] = mapped_column(
        SAEnum(TestCaseCategory, native_enum=False, length=16), nullable=False, index=True
    )

    # 시험 유형 축: "basic_call" | "performance" | "abnormal" (Phase 1은 basic_call만)
    test_type: Mapped[TestCaseType] = mapped_column(
        SAEnum(TestCaseType, native_enum=False, length=16),
        default=TestCaseType.BASIC_CALL,
        nullable=False,
        index=True,
    )

    # 대표 경로 1개: VoLTE는 vctp 설정 파일 경로, McPTT는 메인 SIPp 시나리오(XML) 경로.
    config_ref: Mapped[str] = mapped_column(String(512), nullable=False)

    # 프로토콜별 부가 파라미터 (자유 JSON 구조, 예시는 완료 보고 참고).
    # VoLTE 예: {"dest_path": ..., "restart_cmd": ..., "vcs_log_paths": [...]}
    # McPTT 예: {"target_ip": ..., "target_port": ..., "call_rate": ..., "max_calls": ...}
    protocol_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # 판정 기준 (CLAUDE.md §9의 규칙 엔진이 파싱 결과와 비교).
    # 예: {"required_events": [...], "forbidden_patterns": [...], "max_duration_sec": 30}
    pass_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # testcases/{volte,mcptt}/*.yaml 중 이 레코드와 동기화된 파일의 저장소 루트 기준
    # 상대 경로. YAML <-> DB 동기화(가져오기/내보내기) 추적용 (완료 보고의 설계 노트 참고).
    yaml_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<TestCase id={self.id} name={self.name!r} category={self.category} test_type={self.test_type}>"
