"""통합 테스트 공통 fixture (CLAUDE.md §3, qa-agent.md).

원칙:
- 테스트마다 격리된 임시 SQLite DB를 쓴다. 기존 코드가 `SessionLocal`을
  여러 모듈에서 `from app.core.database import SessionLocal`로 각자
  바인딩해 재사용하고 있어(app.core.database, app.job_runner.runner,
  app.services.execution_common, app.services.volte.executor,
  app.services.mcptt.executor), 격리를 위해서는 이 5곳 전부를
  monkeypatch해야 한다(단순히 app.core.database.SessionLocal만 바꾸면
  나머지 모듈은 여전히 원래 프로세스 전역 DB를 본다).
- 실제 SSH/SIPp 실행은 이 파일에서 모킹하지 않는다(개별 executor 테스트가
  각자의 방식으로 모킹). 여기서는 DB 격리 + HTTP 클라이언트 + 폴링 속도
  단축만 공통 처리한다.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.core.database as database_module
import app.job_runner.runner as job_runner_module
import app.models  # noqa: F401 - Base.metadata에 전체 모델을 등록시키기 위한 side-effect import
import app.services.execution_common as execution_common_module
import app.services.mcptt.executor as mcptt_executor_module
import app.services.volte.executor as volte_executor_module
from app.main import app as fastapi_app


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[], Session]:
    """테스트 전용 임시 SQLite DB로 모든 `SessionLocal` 참조를 교체한다.

    반환값은 새 Session을 만드는 팩토리(sessionmaker)다. 테스트는
    `db = isolated_db()`로 세션을 얻어 fixture 데이터를 직접 심을 수 있고,
    API 라우터(`Depends(get_db)`)도 동일한 DB를 보게 된다.
    """
    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True
    )
    database_module.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "SessionLocal", session_factory)
    monkeypatch.setattr(job_runner_module, "SessionLocal", session_factory)
    monkeypatch.setattr(execution_common_module, "SessionLocal", session_factory)
    monkeypatch.setattr(volte_executor_module, "SessionLocal", session_factory)
    monkeypatch.setattr(mcptt_executor_module, "SessionLocal", session_factory)

    yield session_factory

    engine.dispose()


@pytest.fixture(autouse=True)
def _fast_completion_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    """`wait_for_completion`의 기본 폴링 간격(2초)을 테스트에서만 단축한다.

    volte/mcptt executor 모듈은 같은 `execution_common.wait_for_completion`
    함수 객체를 그대로 import해서 쓰므로, 한 곳의 `__kwdefaults__`만
    고치면 양쪽 모두에 반영된다.
    """
    monkeypatch.setitem(
        execution_common_module.wait_for_completion.__kwdefaults__, "poll_interval_sec", 0.05
    )


@pytest.fixture
async def client(isolated_db: Callable[[], Session]) -> AsyncIterator[httpx.AsyncClient]:
    """`app.main.app`에 직접 붙는 비동기 HTTP 클라이언트(ASGITransport, 실제 소켓 없음)."""
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
