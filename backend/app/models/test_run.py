"""TestRun 모델 (CLAUDE.md §6).

NOTE(FK 미확정): test_case_id는 testcase-manager-agent가 추가할
`test_cases.id`를 참조할 예정이다. 그 모델이 merge되기 전까지는 순수
문자열 컬럼(느슨한 참조)으로 두고, merge 후 아래 컬럼 정의를
`ForeignKey("test_cases.id")`로 교체한다. 지금 임의로 test_cases 테이블을
만들지 않는다 (해당 모델은 testcase-manager-agent 담당).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum as SAEnum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid4_str() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TestRunStatus(str, enum.Enum):
    """Job Runner가 관리하는 실행 라이프사이클 상태 (CLAUDE.md §3.3).

    NOTE: CLAUDE.md §6 데이터 모델 초안에는 완료 상태가 `passed`로도
    언급되어 있으나(§3.3에서는 `done`), 이 구현에서는 `DONE`을 "실행이
    끝남"이라는 라이프사이클 의미로 쓰고, 실제 Pass/Fail 판정은
    log-parser-callflow-agent가 계산해 `result_summary`에 담는다.
    테스트케이스/판정 스키마 확정 시 testcase-manager-agent와 조율해
    용어를 통일한다.
    """

    PENDING = "pending"
    RUNNING = "running"
    PARSING = "parsing"
    DONE = "done"
    FAILED = "failed"
    ERROR = "error"


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4_str)

    # 느슨한 참조: 실제 FK 제약은 test_cases 테이블 merge 후 추가.
    test_case_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    status: Mapped[TestRunStatus] = mapped_column(
        SAEnum(TestRunStatus, native_enum=False, length=16),
        default=TestRunStatus.PENDING,
        nullable=False,
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 시험 대상 VCS 호스트 (SSH 접속 대상). 실행 시점 기록용 스냅샷.
    target_host: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # storage/logs/{test_case_id}/{run_id}/ 하위 원본 로그 디렉토리 또는 대표 파일 경로.
    raw_log_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 파싱/판정 결과 요약 (JSON 문자열 등). 대용량 로그 원문은 절대 여기 담지 않는다
    # (token-guardian-agent 원칙: 요약만 저장, 원본은 raw_log_path 파일로만 보존).
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<TestRun id={self.id} test_case_id={self.test_case_id} status={self.status}>"
