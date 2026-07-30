"""로그 수집 소스 공통 인터페이스 (CLAUDE.md §4, §9 어댑터 패턴과 동일 철학).

`LogSource`는 원본 로그 "라인"을 그대로 흘려보내는 비동기 제너레이터
인터페이스다. 내용 해석/파싱/판정은 이 모듈의 책임이 아니다
(log-parser-callflow-agent 담당, CLAUDE.md §9). 새 소스(예: 향후 syslog
수신기)를 추가할 때는 이 인터페이스만 구현하면 되고, 이를 소비하는
`CollectorSession`은 전혀 수정할 필요가 없다.

다른 에이전트 사용법:
    from app.services.log_collector.base import LogSource, LogSourceError, RetryPolicy
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class LogSourceError(RuntimeError):
    """소스가 재시도 한도를 초과해 복구 불가능한 상태에 빠졌을 때 발생한다.

    `CollectorSession`은 이 예외를 잡아 해당 소스만 에러 상태로 전이시키고
    (다른 소스는 계속 수집), WebSocket으로 `log_source_error` 이벤트를
    브로드캐스트한다.
    """


@dataclass(frozen=True)
class RetryPolicy:
    """연결 끊김/일시적 읽기 실패 시 재연결 재시도 정책 (지수 백오프).

    `max_retries`가 정수면 연속 그만큼 실패했을 때 `LogSourceError`를
    발생시켜 상위가 해당 소스를 포기하도록 한다. 최소 1줄이라도 성공적으로
    수신하면 연속 실패 카운터는 0으로 리셋된다(일시적 네트워크 문제와 완전한
    장애를 구분).

    **기본값은 `None`(무제한 재시도)이다**(2026-07-30 변경) — 예전 기본값
    5회는 McPTT 성능 시험처럼 시험 하나가 수십 분~그 이상 이어지는 경우,
    그 사이 VCS SSH 연결이 몇 번만 끊겨도(네트워크 순단 등) 로그 스트리밍이
    시험 종료 전에 영구히 멈춰버리는 문제가 실제로 보고됐다(재시도 자체는
    최대 30초 간격으로 계속 시도하므로, 무제한으로 둬도 VCS에 부담을 주지
    않는다 — `stop_event`가 set되면 즉시 멈춘다). 유한 재시도가 정말
    필요한 경우(테스트 등)를 위해 옵션 자체는 남겨둔다.
    """

    max_retries: int | None = None
    initial_backoff: float = 1.0
    max_backoff: float = 30.0
    backoff_multiplier: float = 2.0

    def backoff_seconds(self, attempt: int) -> float:
        """attempt는 1부터 시작하는 연속 실패 횟수."""
        return min(self.initial_backoff * (self.backoff_multiplier ** (attempt - 1)), self.max_backoff)


class LogSource(ABC):
    """단일 원본 로그 스트림 어댑터의 공통 인터페이스.

    구현체(`SshTailSource`, `LocalFileSource` 등)는 `name`(WebSocket 메시지의
    `source` 필드 및 `storage/logs/.../{name}.log` 저장 파일명으로 쓰임)과
    `stream()`만 제공하면 된다.
    """

    name: str

    @abstractmethod
    def stream(self, stop_event: asyncio.Event) -> AsyncIterator[str]:
        """라인 단위 비동기 제너레이터 (각 라인은 개행 문자 제거된 원본 텍스트).

        `stop_event`가 set되면 가능한 빨리(다음 폴링 주기 또는 라인 경계에서)
        스트림을 정상 종료해야 한다. 연결 끊김/일시적 오류는 구현체가 자체
        `RetryPolicy`로 재시도하고, 재시도 한도를 초과하면 `LogSourceError`를
        raise해야 한다.
        """
        raise NotImplementedError
