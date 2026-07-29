"""VoLTE/McPTT 실행기(Executor)가 공유하는 조립 로직 (CLAUDE.md §3, §7).

`services/volte`, `services/mcptt`는 "프로토콜"이 다를 뿐, 로그 수집 완료
판정 -> CallEvent 저장 -> Call Flow 생성 -> Pass/Fail 판정 흐름은 동일하다
(CLAUDE.md §3.1 4~5단계, §3.2 4~6단계). 이 모듈이 그 공통 부분을 담당해
두 Executor가 코드를 중복하지 않게 한다.

다른 에이전트 사용법(주로 backend-agent 자신, 참고용):
    from app.services.execution_common import (
        normalize_log_paths, parse_collected_logs, wait_for_completion, persist_results,
    )
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.call_event import CallEvent, CallEventSource
from app.models.call_flow import CallFlowDiagram
from app.services.callflow.generator import Protocol as CallFlowProtocol
from app.services.callflow.generator import generate_mermaid
from app.services.callflow.rules import PassFailResult, evaluate_pass_fail
from app.services.log_parser.base import LogAdapter, assign_sequence, build_call_events, read_file_lines
from app.services.log_parser.sipp_adapter import SippLogAdapter
from app.services.log_parser.vcmc_adapter import VcmcLogAdapter
from app.services.log_parser.vcmm_adapter import VcmmLogAdapter
from app.services.log_parser.vcsm_adapter import VcsmLogAdapter
from app.services.log_parser.vctp_adapter import VctpLogAdapter
from app.ws.manager import manager

logger = logging.getLogger(__name__)

# `CollectorSource.source.name`(= 저장 파일명, 예: "vcsm_log")과 그 내용을 해석할
# LogAdapter의 매핑. CallEventSource enum 값과 이름 규칙이 동일하다
# (`<프로세스>_log`, CLAUDE.md §9.1).
ADAPTERS_BY_LOG_NAME: dict[str, LogAdapter] = {
    "vcsm_log": VcsmLogAdapter(),
    "vcmm_log": VcmmLogAdapter(),
    "vctp_log": VctpLogAdapter(),
    "vcmc_log": VcmcLogAdapter(),
    "sipp_log": SippLogAdapter(),
}

SOURCE_BY_LOG_NAME: dict[str, CallEventSource] = {
    "vcsm_log": CallEventSource.VCSM_LOG,
    "vcmm_log": CallEventSource.VCMM_LOG,
    "vctp_log": CallEventSource.VCTP_LOG,
    "vcmc_log": CallEventSource.VCMC_LOG,
    "sipp_log": CallEventSource.SIPP_LOG,
}


def log_paths_to_named(paths: Sequence[str]) -> dict[str, str]:
    """`["/var/log/vcs/vcsm.log", ...]` -> `{"vcsm_log": "/var/log/vcs/vcsm.log", ...}`.

    파일명 stem 기준으로 `<stem>_log` 이름을 부여한다(`ADAPTERS_BY_LOG_NAME`
    키 규칙과 동일). `TestCase.protocol_params["vcs_log_paths"]`가 리스트
    형태일 때 사용한다.
    """
    named: dict[str, str] = {}
    for p in paths:
        stem = Path(p).stem
        named[f"{stem}_log"] = p
    return named


def normalize_log_paths(vcs_log_paths: Sequence[str] | dict[str, str]) -> dict[str, str]:
    """`protocol_params["vcs_log_paths"]`를 `{log_name: remote_path}` 형태로 정규화.

    리스트(`["/path/vcsm.log", ...]`)와 dict(`{"vcsm_log": "/path/vcsm.log"}`)
    양쪽 형태를 모두 허용한다 — testcase-manager-agent 예시 YAML은 리스트
    형태(`vcs_log_paths: [...]`)를 쓰므로 이를 우선 지원한다.
    """
    if isinstance(vcs_log_paths, dict):
        return dict(vcs_log_paths)
    return log_paths_to_named(vcs_log_paths)


def parse_collected_logs(run_dir: Path, log_names: Sequence[str], run_id: str) -> list[CallEvent]:
    """`run_dir`에 저장된 로그 파일들을 각 어댑터로 파싱해 시간순으로 병합한다.

    반환값은 아직 DB에 추가(add)되지 않은 `CallEvent` 인스턴스 리스트다.
    호출자가 최종 확정 시점에 한 번만 커밋한다(중간 폴링 단계에서는 판정만
    수행하고 저장하지 않는다). 대용량 로그를 한 번에 문자열로 읽지 않고
    `read_file_lines()`로 라인 스트리밍한다 (token-guardian-agent 원칙).
    """
    merged: list[CallEvent] = []
    for name in log_names:
        adapter = ADAPTERS_BY_LOG_NAME.get(name)
        if adapter is None:
            logger.warning("parse_collected_logs: no adapter registered for log name=%s", name)
            continue
        log_path = run_dir / f"{name}.log"
        if not log_path.exists():
            continue
        events = build_call_events(run_id, adapter.source, adapter.parse(read_file_lines(str(log_path))))
        merged.extend(events)
    return assign_sequence(merged)


@dataclass
class CompletionResult:
    events: list[CallEvent]
    pass_fail: PassFailResult
    timed_out: bool


async def wait_for_completion(
    *,
    run_dir: Path,
    log_names: Sequence[str],
    run_id: str,
    pass_criteria: dict[str, Any] | None,
    timeout_sec: float,
    poll_interval_sec: float = 2.0,
) -> CompletionResult:
    """수집된 로그를 주기적으로 재파싱해 Pass 조건 충족 또는 타임아웃까지 대기한다.

    CLAUDE.md §13 TBD: "완료" 판정 기준(로그 패턴 vs 고정 대기시간)이
    미확정이므로, 이 함수는 두 정책을 절충한다 — `pass_criteria`를 만족하면
    즉시 종료하고, 아니면 `timeout_sec`까지 폴링한 뒤 그 시점까지 수집된
    이벤트로 최종 판정한다(타임아웃 시 `timed_out=True`와 함께 그 시점의
    Pass/Fail 결과를 그대로 반환 — 대부분 Fail이겠지만 강제하지 않는다).
    """
    deadline = time.monotonic() + timeout_sec
    events: list[CallEvent] = []
    result = PassFailResult(passed=False, reasons=["polling not started"])

    while True:
        events = parse_collected_logs(run_dir, log_names, run_id)
        # CLAUDE.md §8-4 "진행 중 부분적으로" 렌더링: 최종 확정(persist_results)을
        # 기다리지 않고, 폴링마다 그때까지 모인 이벤트로 Call Flow를 미리
        # 갱신해서 WS로 push한다 — 실행이 끝나야만 다이어그램이 나타나던
        # 문제(대시보드에서 "실시간"으로 안 느껴진다는 피드백)를 해결한다.
        await persist_call_flow(run_id, events)
        result = evaluate_pass_fail(events, pass_criteria)
        if result.passed:
            return CompletionResult(events=events, pass_fail=result, timed_out=False)
        if time.monotonic() >= deadline:
            return CompletionResult(events=events, pass_fail=result, timed_out=True)
        await asyncio.sleep(poll_interval_sec)


def _upsert_call_flow(
    db: Session, run_id: str, events: list[CallEvent], protocol: CallFlowProtocol | None
) -> str:
    """`CallFlowDiagram`을 run_id 기준으로 upsert한다 (커밋은 호출자 책임).

    진행 중 미리보기(`persist_call_flow`)와 최종 확정(`persist_results`)이
    이 로직을 공유한다 — 몇 번을 덮어써도 항상 run_id당 최신 다이어그램
    하나만 남는다.
    """
    mermaid_source = generate_mermaid(events, protocol=protocol)
    existing = db.execute(
        select(CallFlowDiagram).where(CallFlowDiagram.run_id == run_id)
    ).scalar_one_or_none()
    if existing is not None:
        existing.mermaid_source = mermaid_source
    else:
        db.add(CallFlowDiagram(run_id=run_id, mermaid_source=mermaid_source))
    return mermaid_source


async def _broadcast_call_flow(run_id: str, mermaid_source: str) -> None:
    await manager.broadcast_to_run(
        run_id,
        {
            "type": "call_flow",
            "run_id": run_id,
            "mermaid_source": mermaid_source,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _persist_call_flow_sync(run_id: str, events: list[CallEvent]) -> str:
    db = SessionLocal()
    try:
        mermaid_source = _upsert_call_flow(db, run_id, events, protocol=None)
        db.commit()
        return mermaid_source
    finally:
        db.close()


async def persist_call_flow(run_id: str, events: list[CallEvent]) -> None:
    """실행 도중 그때까지 수집된 이벤트만으로 Call Flow를 미리 갱신하고 WS로 push한다.

    `events`가 비어있으면(아직 아무 로그도 안 들어온 초반) 건너뛴다 —
    프로토콜 자동판별(`generate_mermaid`의 `protocol=None`)이 기본값(volte)으로
    잘못 표시되는 걸 막고, 의미 없는 DB 쓰기/브로드캐스트도 줄인다. `CallEvent`
    자체는 여기서 저장하지 않는다(최종 확정은 `persist_results`가 한 번만
    수행 — 매 폴링마다 재파싱한 이벤트를 그때마다 insert하면 중복이 생긴다).
    """
    if not events:
        return
    mermaid_source = await asyncio.to_thread(_persist_call_flow_sync, run_id, events)
    await _broadcast_call_flow(run_id, mermaid_source)


def _persist_results_sync(
    run_id: str, events: list[CallEvent], protocol: CallFlowProtocol | None
) -> str:
    db = SessionLocal()
    try:
        for event in events:
            db.add(event)
        mermaid_source = _upsert_call_flow(db, run_id, events, protocol)
        db.commit()
        return mermaid_source
    finally:
        db.close()


async def persist_results(
    run_id: str, events: list[CallEvent], protocol: CallFlowProtocol | None = None
) -> str:
    """최종 확정된 `CallEvent`들을 DB에 저장하고 Call Flow(Mermaid)를 생성/upsert한다.

    DB I/O는 동기 SQLAlchemy Session이므로 `asyncio.to_thread`로 감싼다
    (job_runner의 `set_status`와 동일한 패턴). 반환값은 저장된
    mermaid_source(작은 텍스트, 대용량 아님). 마지막으로 한 번 더 WS push해서
    최종 상태를 폴링 없이 즉시 반영할 수 있게 한다.
    """
    mermaid_source = await asyncio.to_thread(_persist_results_sync, run_id, events, protocol)
    await _broadcast_call_flow(run_id, mermaid_source)
    return mermaid_source
