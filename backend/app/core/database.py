"""SQLAlchemy 엔진/세션/Base 정의.

다른 에이전트 사용법:
    from app.core.database import Base, get_db

    class TestCase(Base):
        __tablename__ = "test_cases"
        ...

    @router.get(...)
    def handler(db: Session = Depends(get_db)):
        ...

DB는 SQLite로 시작하되, DATABASE_URL 환경변수만 바꾸면 PostgreSQL 등으로
전환 가능하도록 엔진 생성 로직을 URL 기반으로 유지한다.
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    """모든 SQLAlchemy 모델의 공통 베이스.

    TestCase(testcase-manager-agent), TestRun(backend-agent), CallEvent /
    CallFlowDiagram(log-parser-callflow-agent) 등은 전부 이 Base를 상속한다.
    """


def _ensure_sqlite_dir(database_url: str) -> None:
    """sqlite 파일 DB의 부모 디렉토리가 없으면 생성한다."""
    if not database_url.startswith("sqlite"):
        return
    # sqlite:///relative/path.db 또는 sqlite:////absolute/path.db 형태만 처리
    raw_path = database_url.split("///", maxsplit=1)[-1]
    if not raw_path:
        return
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _make_engine() -> Engine:
    connect_args: dict[str, object] = {}
    if settings.database_url.startswith("sqlite"):
        _ensure_sqlite_dir(settings.database_url)
        connect_args["check_same_thread"] = False
    return create_engine(settings.database_url, connect_args=connect_args, future=True)


engine: Engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI Depends()로 주입하는 DB 세션 제너레이터."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_storage_dirs() -> None:
    """앱 시작 시 필요한 storage 하위 디렉토리를 보장한다.

    실제 테이블 생성은 Alembic 마이그레이션으로 관리하고, 여기서는
    디렉토리 준비(로그 저장 경로 등)만 수행한다.
    """
    settings.log_storage_path.mkdir(parents=True, exist_ok=True)
    settings.db_storage_path.mkdir(parents=True, exist_ok=True)
