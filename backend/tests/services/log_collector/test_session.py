"""CollectorSession 단위 테스트.

WebSocket 매니저는 실제 연결 없이 `broadcast_to_run`만 monkeypatch해서
호출 인자(메시지 스키마)를 검증한다. 저장은 tmp_path 기반 실제 파일에 쓴다.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.services.log_collector import session as session_module
from app.services.log_collector.base import LogSource, LogSourceError
from app.services.log_collector.local_source import LocalFileSource
from app.services.log_collector.session import CollectorSession, CollectorSource


class _ImmediateFailSource(LogSource):
    """항상 즉시 LogSourceError를 발생시키는 테스트용 소스."""

    def __init__(self, name: str, message: str = "boom") -> None:
        self.name = name
        self._message = message

    async def stream(self, stop_event: asyncio.Event):
        raise LogSourceError(self._message)
        yield ""  # pragma: no cover - 도달하지 않음 (제너레이터 형태 유지용)


@pytest.fixture
def broadcasts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    async def _fake_broadcast(run_id: str, message: dict[str, Any]) -> None:
        captured.append(message)

    monkeypatch.setattr(session_module.manager, "broadcast_to_run", _fake_broadcast)
    return captured


@pytest.mark.asyncio
async def test_session_saves_and_broadcasts_lines(tmp_path: Path, broadcasts: list[dict[str, Any]]) -> None:
    src_file = tmp_path / "src" / "sipp.log"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("hello\nworld\n", encoding="utf-8")

    settings = Settings(storage_dir=str(tmp_path / "storage"))
    source = LocalFileSource("sipp_log", src_file, from_beginning=True, poll_interval=0.01)
    session = CollectorSession(
        run_id="run-1",
        test_case_id="tc-1",
        sources=[CollectorSource(source, channel="sipp_log")],
        settings=settings,
    )

    await session.start()
    # 두 줄이 수집/브로드캐스트될 때까지 대기
    for _ in range(200):
        if len(broadcasts) >= 2:
            break
        await asyncio.sleep(0.02)
    await session.stop()

    log_path = tmp_path / "storage" / "logs" / "tc-1" / "run-1" / "sipp_log.log"
    assert log_path.read_text(encoding="utf-8") == "hello\nworld\n"

    log_messages = [m for m in broadcasts if m["type"] == "log"]
    assert [m["line"] for m in log_messages] == ["hello", "world"]
    assert log_messages[0]["run_id"] == "run-1"
    assert log_messages[0]["channel"] == "sipp_log"
    assert log_messages[0]["source"] == "sipp_log"
    assert log_messages[0]["seq"] == 1
    assert log_messages[1]["seq"] == 2
    assert "ts" in log_messages[0]


@pytest.mark.asyncio
async def test_session_reports_permanent_source_error(tmp_path: Path, broadcasts: list[dict[str, Any]]) -> None:
    settings = Settings(storage_dir=str(tmp_path / "storage"))
    source = _ImmediateFailSource("vcsm_log", message="max retries exceeded")
    session = CollectorSession(
        run_id="run-2",
        test_case_id="tc-2",
        sources=[CollectorSource(source, channel="vcs_log")],
        settings=settings,
    )

    await session.start()
    await session.wait()

    assert session.errors == {"vcsm_log": "max retries exceeded"}
    error_messages = [m for m in broadcasts if m["type"] == "log_source_error"]
    assert len(error_messages) == 1
    assert error_messages[0]["source"] == "vcsm_log"
    assert error_messages[0]["channel"] == "vcs_log"
    assert error_messages[0]["message"] == "max retries exceeded"


@pytest.mark.asyncio
async def test_session_run_dir_layout(tmp_path: Path, broadcasts: list[dict[str, Any]]) -> None:
    settings = Settings(storage_dir=str(tmp_path / "storage"))
    session = CollectorSession(run_id="run-3", test_case_id="tc-3", sources=[], settings=settings)

    assert session.run_dir == tmp_path / "storage" / "logs" / "tc-3" / "run-3"

    await session.start()
    assert session.run_dir.is_dir()
    await session.stop()


@pytest.mark.asyncio
async def test_session_multiple_sources_independent_channels(
    tmp_path: Path, broadcasts: list[dict[str, Any]]
) -> None:
    vcs_file = tmp_path / "vcsm.log"
    vcs_file.write_text("SIP INVITE\n", encoding="utf-8")
    sipp_file = tmp_path / "sipp.log"
    sipp_file.write_text("SIPp stat\n", encoding="utf-8")

    settings = Settings(storage_dir=str(tmp_path / "storage"))
    session = CollectorSession(
        run_id="run-4",
        test_case_id="tc-4",
        sources=[
            CollectorSource(LocalFileSource("vcsm_log", vcs_file, poll_interval=0.01), channel="vcs_log"),
            CollectorSource(LocalFileSource("sipp_log", sipp_file, poll_interval=0.01), channel="sipp_log"),
        ],
        settings=settings,
    )

    await session.start()
    for _ in range(200):
        if len(broadcasts) >= 2:
            break
        await asyncio.sleep(0.02)
    await session.stop()

    channels = {m["source"]: m["channel"] for m in broadcasts if m["type"] == "log"}
    assert channels == {"vcsm_log": "vcs_log", "sipp_log": "sipp_log"}
    assert (session.run_dir / "vcsm_log.log").read_text(encoding="utf-8") == "SIP INVITE\n"
    assert (session.run_dir / "sipp_log.log").read_text(encoding="utf-8") == "SIPp stat\n"
