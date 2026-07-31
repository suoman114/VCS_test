"""시험 실행기(Executor) 공통 인터페이스 + 레지스트리 (CLAUDE.md §7).

`services/volte`, `services/mcptt` 는 "프로토콜" 축이고, `test_type`
(basic_call/performance/abnormal)은 별도 축이다. 실행기는 항상
`(protocol, test_type)` 조합으로 조회한다.

VoLTE/McPTT 기본 호처리 실행기는 아래처럼 등록되어 있다
(`app/services/volte/executor.py`, `app/services/mcptt/executor.py` 참고):

    @executor_registry.register(protocol="volte", test_type="basic_call")
    class VolteBasicCallExecutor(TestExecutor):
        protocol = "volte"
        test_type = "basic_call"

        async def run(self, test_case: TestCaseLike) -> TestRun:
            ...

다른 에이전트 사용법:
    from app.services.executor_base import TestExecutor, TestCaseLike, executor_registry

    executor_cls = executor_registry.get(test_case.category, test_case.test_type)
    # run_id는 호출자(app.api.test_runs)가 미리 생성한 TestRun.id를 그대로 넘긴다.
    # (인터페이스 자체는 CLAUDE.md §7이 요구하는 `run(test_case) -> TestRun` 그대로
    # 유지하고, run_id는 생성자로 주입한다 — registry.create()의 *args/**kwargs가
    # 이 용도로 이미 예약되어 있었다.)
    executor = executor_registry.create(test_case.category, test_case.test_type, run_id=test_run.id)
    test_run = await executor.run(test_case)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from app.models.test_run import TestRun


@runtime_checkable
class TestCaseLike(Protocol):
    """testcase-manager-agent가 정의할 TestCase 모델의 최소 인터페이스.

    실제 TestCase 클래스가 merge되기 전까지 Executor 구현체는 이 Protocol을
    만족하는 어떤 객체(SQLAlchemy 모델 인스턴스, DTO 등)도 받아들일 수 있다.
    """

    id: str
    category: str  # "volte" | "mcptt"
    test_type: str  # "basic_call" | "performance" | "abnormal" (Phase 1: basic_call만)


class TestExecutor(ABC):
    """모든 시험 실행기가 구현해야 하는 공통 인터페이스.

    `run(test_case) -> TestRun` 시그니처 자체는 CLAUDE.md §7이 요구하는 그대로
    유지한다. 다만 어떤 TestRun(run_id)에 대해 실행하는지는 생성자로
    주입한다 — 호출자(`app.api.test_runs`)가 TestRun 레코드를 먼저 생성해
    즉시 클라이언트에 반환(`status=pending`)한 뒤, 그 `run_id`로 실행기를
    생성하고 `job_runner.submit(run_id, ...)`으로 백그라운드 실행한다.
    """

    protocol: str
    test_type: str

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    @abstractmethod
    async def run(self, test_case: TestCaseLike) -> TestRun:
        """시험을 실행하고 최종(혹은 실행 시작 시점의) TestRun을 반환한다.

        구현체는 내부적으로 job_runner를 통해 상태 전이
        (pending -> running -> parsing -> done/failed/error)를 관리해야 한다.
        """
        raise NotImplementedError


class TestExecutorRegistry:
    """(protocol, test_type) -> TestExecutor 구현 클래스 레지스트리."""

    def __init__(self) -> None:
        self._registry: dict[tuple[str, str], type[TestExecutor]] = {}

    def register(self, protocol: str, test_type: str):
        def decorator(cls: type[TestExecutor]) -> type[TestExecutor]:
            self._registry[(protocol, test_type)] = cls
            return cls

        return decorator

    def get(self, protocol: str, test_type: str) -> type[TestExecutor]:
        try:
            return self._registry[(protocol, test_type)]
        except KeyError as exc:
            raise LookupError(
                f"No TestExecutor registered for protocol={protocol!r}, test_type={test_type!r}"
            ) from exc

    def create(self, protocol: str, test_type: str, *args: Any, **kwargs: Any) -> TestExecutor:
        return self.get(protocol, test_type)(*args, **kwargs)

    def is_registered(self, protocol: str, test_type: str) -> bool:
        return (protocol, test_type) in self._registry


executor_registry = TestExecutorRegistry()
