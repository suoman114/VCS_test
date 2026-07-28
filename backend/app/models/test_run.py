"""TestRun 모델 (CLAUDE.md §6).

`test_case_id`는 testcase-manager-agent가 merge한 `test_cases.id`
(String(36))를 참조하는 실제 `ForeignKey("test_cases.id")`이다 (Wave 3에서
느슨한 String(64) 컬럼에서 교체됨).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid4_str() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TestRunStatus(str, enum.Enum):
    """Job Runner가 관리하는 실행 라이프사이클 상태 (CLAUDE.md §3.3).

    Wave 3에서 VoLTE/McPTT Executor를 조립하며 아래처럼 의미를 확정했다
    (테스트케이스/판정 스키마 확정 시 testcase-manager-agent와 재조율 가능):

    - `DONE`: 실행이 끝났고 `evaluate_pass_fail()` 결과 Pass. 즉 CLAUDE.md
      §6 초안의 `passed`에 해당한다.
    - `FAILED`: 실행은 끝났지만(로그 수집/파싱 자체는 성공) Pass 조건을
      만족하지 못함(criteria 불충족 또는 판정 타임아웃 포함).
    - `ERROR`: 실행 인프라 자체가 실패(SSH 연결 실패, SIPp 실행 실패, 예외
      등). `job_runner._run_wrapper`가 unhandled exception을 여기로 수렴시킨다.

    `result_summary`(JSON 문자열)에 `passed`/`reasons`/`timed_out`/
    `event_count` 등 판정 근거 요약을 담는다 (원본 로그는 절대 담지 않음).
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

    test_case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("test_cases.id"), index=True, nullable=False
    )

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
