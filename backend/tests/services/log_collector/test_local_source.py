"""LocalFileSource 단위 테스트 (실제 임시 파일 사용, SSH 없음)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.log_collector.base import LogSourceError, RetryPolicy
from app.services.log_collector.local_source import LocalFileSource

FAST_RETRY = RetryPolicy(max_retries=3, initial_backoff=0.01, max_backoff=0.02)


async def _collect(source: LocalFileSource, stop_event: asyncio.Event, count: int) -> list[str]:
    """count개의 라인을 모으면 stop_event를 set하고 반환한다."""
    lines: list[str] = []
    async for line in source.stream(stop_event):
        lines.append(line)
        if len(lines) >= count:
            stop_event.set()
    return lines


@pytest.mark.asyncio
async def test_reads_existing_file_from_beginning(tmp_path: Path) -> None:
    log_file = tmp_path / "sipp.log"
    log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

    source = LocalFileSource("sipp_log", log_file, from_beginning=True, poll_interval=0.01, retry_policy=FAST_RETRY)
    stop_event = asyncio.Event()

    lines = await asyncio.wait_for(_collect(source, stop_event, 3), timeout=5)

    assert lines == ["line1", "line2", "line3"]


@pytest.mark.asyncio
async def test_tails_appended_lines(tmp_path: Path) -> None:
    log_file = tmp_path / "sipp.log"
    log_file.write_text("old-line\n", encoding="utf-8")

    source = LocalFileSource("sipp_log", log_file, from_beginning=False, poll_interval=0.01, retry_policy=FAST_RETRY)
    stop_event = asyncio.Event()

    async def _append_later() -> None:
        await asyncio.sleep(0.05)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write("new-line-1\n")
            fh.write("new-line-2\n")

    append_task = asyncio.create_task(_append_later())
    lines = await asyncio.wait_for(_collect(source, stop_event, 2), timeout=5)
    await append_task

    # from_beginning=False이므로 기존 "old-line"은 건너뛰고 새로 추가된 라인만 수집한다.
    assert lines == ["new-line-1", "new-line-2"]


@pytest.mark.asyncio
async def test_waits_for_file_creation(tmp_path: Path) -> None:
    log_file = tmp_path / "not-yet.log"

    source = LocalFileSource("sipp_log", log_file, from_beginning=True, poll_interval=0.01, retry_policy=FAST_RETRY)
    stop_event = asyncio.Event()

    async def _create_later() -> None:
        await asyncio.sleep(0.03)
        log_file.write_text("first-line\n", encoding="utf-8")

    create_task = asyncio.create_task(_create_later())
    lines = await asyncio.wait_for(_collect(source, stop_event, 1), timeout=5)
    await create_task

    assert lines == ["first-line"]


@pytest.mark.asyncio
async def test_stop_event_ends_stream_cleanly(tmp_path: Path) -> None:
    log_file = tmp_path / "sipp.log"
    log_file.write_text("only-line\n", encoding="utf-8")

    source = LocalFileSource("sipp_log", log_file, from_beginning=True, poll_interval=0.01, retry_policy=FAST_RETRY)
    stop_event = asyncio.Event()

    collected: list[str] = []

    async def _run() -> None:
        async for line in source.stream(stop_event):
            collected.append(line)

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.05)  # 라인 하나를 읽고 폴링 대기 상태에 들어가도록
    stop_event.set()
    await asyncio.wait_for(task, timeout=5)

    assert collected == ["only-line"]


@pytest.mark.asyncio
async def test_missing_file_exceeds_retries_raises() -> None:
    missing_path = Path("/nonexistent/dir/never-created.log")
    source = LocalFileSource(
        "sipp_log", missing_path, from_beginning=True, poll_interval=0.01, retry_policy=FAST_RETRY
    )
    stop_event = asyncio.Event()

    with pytest.raises(LogSourceError):
        async for _ in source.stream(stop_event):
            pass
