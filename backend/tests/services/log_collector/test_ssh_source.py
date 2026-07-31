"""SshTailSource 단위 테스트.

실제 SSH 연결은 만들지 않는다 — `app.services.log_collector.ssh_source.SSHConnector`를
페이크로 monkeypatch해서 (1) 정상 스트리밍, (2) 연결 끊김 후 재연결,
(3) 재시도 한도 초과 시 LogSourceError를 검증한다.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.services.log_collector import ssh_source as ssh_source_module
from app.services.log_collector.base import LogSourceError, RetryPolicy
from app.services.log_collector.ssh_source import SshTailSource

FAST_RETRY = RetryPolicy(max_retries=2, initial_backoff=0.01, max_backoff=0.02)


class _FakeConnection:
    """`SSHConnector`를 대체하는 페이크. 매 재연결(인스턴스 생성)마다 다른 동작을 낼 수 있다."""

    def __init__(self, behaviors: list[str]) -> None:
        # behaviors: 이 페이크 클래스 전체(=재연결 시도들)에 걸쳐 공유되는 시나리오 큐.
        self._behaviors = behaviors
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def tail_file(
        self, remote_path: str, *, from_beginning: bool = False, stop_event: asyncio.Event | None = None
    ) -> AsyncIterator[str]:
        if not self._behaviors:
            return
        behavior = self._behaviors.pop(0)
        if behavior == "lines_then_drop":
            yield "line-1"
            yield "line-2"
            raise ConnectionResetError("simulated connection drop")
        elif behavior == "lines_then_stop":
            yield "line-3"
            if stop_event is not None:
                stop_event.set()
        elif behavior == "always_fail":
            raise ConnectionResetError("simulated permanent failure")
        else:
            raise AssertionError(f"unknown behavior: {behavior}")


def _make_fake_connector_factory(behaviors: list[str]):
    """SSHConnector(target) 생성자를 흉내내는 팩토리. 매 호출마다 같은 behaviors 큐를 공유."""

    def factory(target=None):
        return _FakeConnection(behaviors)

    return factory


@pytest.mark.asyncio
async def test_reconnects_after_connection_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    behaviors = ["lines_then_drop", "lines_then_stop"]
    monkeypatch.setattr(ssh_source_module, "SSHConnector", _make_fake_connector_factory(behaviors))

    source = SshTailSource("vcsm_log", "/var/log/vcs/vcsm.log", retry_policy=FAST_RETRY)
    stop_event = asyncio.Event()

    lines = [line async for line in source.stream(stop_event)]

    assert lines == ["line-1", "line-2", "line-3"]
    assert behaviors == []  # 두 시나리오 모두 소비됨 (재연결 1회 발생)


@pytest.mark.asyncio
async def test_exceeds_max_retries_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    behaviors = ["always_fail", "always_fail", "always_fail", "always_fail"]
    monkeypatch.setattr(ssh_source_module, "SSHConnector", _make_fake_connector_factory(behaviors))

    source = SshTailSource("vcsm_log", "/var/log/vcs/vcsm.log", retry_policy=FAST_RETRY)
    stop_event = asyncio.Event()

    with pytest.raises(LogSourceError):
        async for _ in source.stream(stop_event):
            pass


@pytest.mark.asyncio
async def test_default_retry_policy_never_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-07-30 실 사용 리포트: McPTT 성능 시험처럼 시험 하나가 길게 이어지면
    그 사이 VCS SSH 연결이 몇 번만 끊겨도(예전 기본값 5회) 로그 스트리밍이
    시험 종료 전에 영구히 멈춰버렸다. 기본 `RetryPolicy()`(max_retries=None)는
    실패가 예전 기본값(5회)보다 많이 반복돼도 `LogSourceError`를 던지지
    않고 계속 재시도해야 한다."""
    # 예전 기본값(5)보다 많은 연속 실패 뒤에야 성공하는 시나리오.
    behaviors = ["always_fail"] * 8 + ["lines_then_stop"]
    monkeypatch.setattr(ssh_source_module, "SSHConnector", _make_fake_connector_factory(behaviors))

    source = SshTailSource(
        "vcsm_log",
        "/var/log/vcs/vcsm.log",
        retry_policy=RetryPolicy(initial_backoff=0.001, max_backoff=0.002),  # max_retries 생략 -> 기본값(무제한)
    )
    stop_event = asyncio.Event()

    lines = [line async for line in source.stream(stop_event)]

    assert lines == ["line-3"]
    assert behaviors == []  # 8번의 실패를 전부 재시도로 넘기고 9번째 시나리오까지 도달함


@pytest.mark.asyncio
async def test_stop_event_during_backoff_ends_without_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    behaviors = ["lines_then_drop"]
    monkeypatch.setattr(ssh_source_module, "SSHConnector", _make_fake_connector_factory(behaviors))

    source = SshTailSource(
        "vcsm_log",
        "/var/log/vcs/vcsm.log",
        retry_policy=RetryPolicy(max_retries=5, initial_backoff=0.2, max_backoff=0.2),
    )
    stop_event = asyncio.Event()

    collected: list[str] = []

    async def _run() -> None:
        async for line in source.stream(stop_event):
            collected.append(line)

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.05)  # 첫 두 줄을 받고 drop된 뒤, backoff 대기 중이 되도록
    stop_event.set()
    await asyncio.wait_for(task, timeout=5)

    assert collected == ["line-1", "line-2"]
