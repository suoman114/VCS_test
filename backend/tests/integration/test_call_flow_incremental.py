"""`execution_common.persist_call_flow` 통합 테스트.

Call Flow가 실행 종료 후 딱 한 번만 생성되던 문제(대시보드에서 "실시간으로
안 느껴진다"는 피드백, 2026-07-29) — `wait_for_completion`의 폴링마다
`persist_call_flow`를 호출해 그때까지 모인 이벤트로 미리 갱신하고 WS로
push하도록 고쳤다. 여기서는 폴링 루프의 타이밍과 분리해서
`persist_call_flow` 자체의 핵심 계약만 검증한다:
  - 이벤트가 아직 없으면(초반) DB/브로드캐스트 둘 다 건너뛴다.
  - 이벤트가 있으면 run_id 기준으로 upsert(여러 번 불러도 행 하나만 유지)
    하고, WS로 "call_flow" 타입 메시지를 push한다.
"""
from __future__ import annotations

from pathlib import Path

import app.services.execution_common as execution_common_module
import pytest
from app.models.call_event import CallEvent, CallEventSource
from app.models.call_flow import CallFlowDiagram
from app.services.execution_common import persist_call_flow
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VOLTE_VCSM_LOG = _REPO_ROOT / "docs" / "log_samples" / "volte" / "vcsm.log"


def _make_event(run_id: str, seq_no: int, parsed_type: str, raw_line: str = "") -> CallEvent:
    return CallEvent(
        run_id=run_id,
        source=CallEventSource.VCSM_LOG,
        raw_line=raw_line,
        parsed_type=parsed_type,
        seq_no=seq_no,
    )


@pytest.mark.asyncio
async def test_persist_call_flow_skips_when_no_events(isolated_db, monkeypatch: pytest.MonkeyPatch) -> None:
    broadcasts: list[dict[str, object]] = []

    async def _fake_broadcast(run_id: str, message: dict[str, object]) -> None:
        broadcasts.append(message)

    monkeypatch.setattr(execution_common_module.manager, "broadcast_to_run", _fake_broadcast)

    await persist_call_flow("run-empty", [])

    db = isolated_db()
    try:
        existing = db.execute(
            select(CallFlowDiagram).where(CallFlowDiagram.run_id == "run-empty")
        ).scalar_one_or_none()
    finally:
        db.close()

    assert existing is None
    assert broadcasts == []


@pytest.mark.asyncio
async def test_persist_call_flow_upserts_and_broadcasts(
    isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    broadcasts: list[dict[str, object]] = []

    async def _fake_broadcast(run_id: str, message: dict[str, object]) -> None:
        broadcasts.append(message)

    monkeypatch.setattr(execution_common_module.manager, "broadcast_to_run", _fake_broadcast)

    run_id = "run-partial"
    partial_events = [_make_event(run_id, 1, "SIP_INVITE")]
    await persist_call_flow(run_id, partial_events)

    db = isolated_db()
    try:
        first = db.execute(
            select(CallFlowDiagram).where(CallFlowDiagram.run_id == run_id)
        ).scalar_one()
        first_source = first.mermaid_source
    finally:
        db.close()

    assert "SIP_INVITE" in first_source
    assert len(broadcasts) == 1
    assert broadcasts[0]["type"] == "call_flow"
    assert broadcasts[0]["run_id"] == run_id
    assert broadcasts[0]["mermaid_source"] == first_source

    # 폴링이 이어지며 이벤트가 더 쌓였다고 가정 — 같은 run_id는 새 행이 아니라 갱신돼야 한다.
    fuller_events = partial_events + [_make_event(run_id, 2, "SIP_200OK", raw_line='"reasonCode": 200')]
    await persist_call_flow(run_id, fuller_events)

    db = isolated_db()
    try:
        rows = db.execute(
            select(CallFlowDiagram).where(CallFlowDiagram.run_id == run_id)
        ).scalars().all()
    finally:
        db.close()

    assert len(rows) == 1
    assert "SIP_200OK" in rows[0].mermaid_source
    assert len(broadcasts) == 2


@pytest.mark.asyncio
async def test_wait_for_completion_persists_call_flow_before_pass_criteria_met(
    isolated_db, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """폴링 루프 자체가 매 iteration마다 persist_call_flow를 호출하는지 종단 확인."""
    broadcasts: list[dict[str, object]] = []

    async def _fake_broadcast(run_id: str, message: dict[str, object]) -> None:
        broadcasts.append(message)

    monkeypatch.setattr(execution_common_module.manager, "broadcast_to_run", _fake_broadcast)

    run_id = "run-loop"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    vcsm_log = run_dir / "vcsm_log.log"
    # 첫 SIP 블록 하나(INVITE, 59줄, 트레일러 " - (RecordHandler.java:132)"까지)만
    # 떼어 써서 VcsmLogAdapter가 실제로 파싱할 수 있는 최소 fixture를 만든다.
    sample_lines = _VOLTE_VCSM_LOG.read_text(encoding="utf-8").splitlines()[:59]
    vcsm_log.write_text("\n".join(sample_lines) + "\n", encoding="utf-8")

    # pass_criteria가 절대 만족되지 않게 해서(존재하지 않는 parsed_type 요구)
    # 반드시 타임아웃 경로로만 끝나게 하고, 그 전에 폴링이 최소 1회는
    # 돌면서 call_flow를 미리 갱신했는지 확인한다.
    completion = await execution_common_module.wait_for_completion(
        run_dir=run_dir,
        log_names=["vcsm_log"],
        run_id=run_id,
        pass_criteria={"required_events": ["NEVER_HAPPENS"]},
        timeout_sec=0.05,
        poll_interval_sec=0.02,
    )

    assert completion.timed_out is True
    assert len(broadcasts) >= 1
    assert broadcasts[0]["type"] == "call_flow"

    db = isolated_db()
    try:
        row = db.execute(
            select(CallFlowDiagram).where(CallFlowDiagram.run_id == run_id)
        ).scalar_one()
    finally:
        db.close()
    assert row.mermaid_source  # 비어있지 않은 다이어그램이 실행 종료 전에 이미 저장돼 있었다
