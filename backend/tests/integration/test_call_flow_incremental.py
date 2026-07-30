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

from datetime import datetime, timezone
from pathlib import Path

import app.api.test_runs as test_runs_module
import app.services.execution_common as execution_common_module
import httpx
import pytest
from app.core.config import Settings
from app.models.call_event import CallEvent, CallEventSource
from app.models.call_flow import CallFlowDiagram
from app.models.test_case import TestCase, TestCaseCategory, TestCaseType
from app.models.test_run import TestRun, TestRunStatus
from app.services.execution_common import persist_call_flow
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VOLTE_VCSM_LOG = _REPO_ROOT / "docs" / "log_samples" / "volte" / "vcsm.log"


def _make_event(run_id: str, seq_no: int, parsed_type: str, raw_line: str = "") -> CallEvent:
    return CallEvent(
        run_id=run_id,
        ts=datetime.now(timezone.utc),
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
    assert broadcasts[0]["messages"] == [
        {"index": 0, "seq_no": 1, "source": "vcsm_log", "call_id": None}
    ]

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
async def test_persist_call_flow_uses_explicit_protocol_instead_of_guessing(
    isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2026-07-30 실 서버 리포트: McPTT 시험 실행 중 Call Flow 참가자 레인이
    처음엔 VCTP/VCSM/VCMM(VoLTE)로 보였다가 몇 초 뒤 SIPp/UE/VCMC로
    바뀌었다 — McPTT는 SIP 시그널링 소스가 vcmc_log 하나뿐이라, 그 로그의
    첫 이벤트가 파싱되기 전(vcmm_log의 RECORDING_* 이벤트만 있는 상태)에는
    `detect_protocol`이 기본값(volte)으로 잘못 추측했기 때문이다. 호출자가
    `protocol`을 명시하면 이벤트 구성과 무관하게 그 값을 그대로 써야 한다."""
    broadcasts: list[dict[str, object]] = []

    async def _fake_broadcast(run_id: str, message: dict[str, object]) -> None:
        broadcasts.append(message)

    monkeypatch.setattr(execution_common_module.manager, "broadcast_to_run", _fake_broadcast)

    run_id = "run-mcptt-early"
    # vcmc_log 이벤트가 아직 하나도 없는 상태(McPTT 시험 초반, vcmm_log의
    # RECORDING_START_REQ만 도착한 시점)를 흉내낸다.
    vcmm_only_events = [
        CallEvent(
            run_id=run_id,
            ts=datetime.now(timezone.utc),
            source=CallEventSource.VCMM_LOG,
            raw_line="message send ok.",
            parsed_type="RECORDING_START_REQ",
            seq_no=1,
        )
    ]

    await persist_call_flow(run_id, vcmm_only_events, protocol="mcptt")

    db = isolated_db()
    try:
        row = db.execute(select(CallFlowDiagram).where(CallFlowDiagram.run_id == run_id)).scalar_one()
    finally:
        db.close()

    assert "participant SIPp_UE as SIPp/UE" in row.mermaid_source
    assert "participant VCTP as VCTP" not in row.mermaid_source


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


@pytest.mark.asyncio
async def test_get_call_flow_api_returns_message_index_for_click_to_log(
    client: httpx.AsyncClient, isolated_db
) -> None:
    """GET /test-runs/{id}/call-flow가 클릭-투-로그용 messages를 CallEvent에서 다시 계산해 반환하는지."""
    run_id = "run-api"
    db = isolated_db()
    try:
        test_case = TestCase(
            id="tc-api",
            name="call-flow-api-fixture",
            category=TestCaseCategory.VOLTE,
            test_type=TestCaseType.BASIC_CALL,
            config_ref="imsVideo30sec.pcap",
            protocol_params={},
            pass_criteria={},
        )
        db.add(test_case)
        db.add(TestRun(id=run_id, test_case_id=test_case.id, status=TestRunStatus.DONE))
        db.add(CallFlowDiagram(run_id=run_id, mermaid_source="sequenceDiagram\n"))
        db.add(_make_event(run_id, 1, "SIP_INVITE"))
        db.add(_make_event(run_id, 2, "SIP_200OK", raw_line='"reasonCode": 200'))
        db.commit()
    finally:
        db.close()

    resp = await client.get(f"/api/test-runs/{run_id}/call-flow")

    assert resp.status_code == 200
    body = resp.json()
    assert body["messages"] == [
        {"index": 0, "seq_no": 1, "source": "vcsm_log", "call_id": None},
        {"index": 1, "seq_no": 2, "source": "vcsm_log", "call_id": None},
    ]


@pytest.mark.asyncio
async def test_events_and_call_flow_fall_back_to_live_parse_while_run_is_still_running(
    client: httpx.AsyncClient, isolated_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실 서버에서 확인된 문제: 실행 중(아직 persist_results 전)에는 CallEvent가
    DB에 하나도 없어서 GET /events, GET /call-flow의 messages가 항상 텅
    비어있었다 — "과거 로그"/클릭-투-로그가 실행 중엔 전혀 동작하지 않았다.
    DB가 비어있으면 storage/logs/{test_case_id}/{run_id}/*.log를 즉석
    파싱해서 채우는 fallback(_load_events)이 실제로 동작하는지 확인한다.
    """
    run_id = "run-live-parse"
    test_case_id = "tc-live-parse"

    isolated_settings = Settings(storage_dir=str(tmp_path / "storage"))
    monkeypatch.setattr(test_runs_module, "get_settings", lambda: isolated_settings)

    run_dir = isolated_settings.log_storage_path / test_case_id / run_id
    run_dir.mkdir(parents=True)
    sample_lines = _VOLTE_VCSM_LOG.read_text(encoding="utf-8").splitlines()[:59]
    (run_dir / "vcsm_log.log").write_text("\n".join(sample_lines) + "\n", encoding="utf-8")

    db = isolated_db()
    try:
        db.add(
            TestCase(
                id=test_case_id,
                name="live-parse-fixture",
                category=TestCaseCategory.VOLTE,
                test_type=TestCaseType.BASIC_CALL,
                config_ref="imsVideo30sec.pcap",
                protocol_params={},
                pass_criteria={},
            )
        )
        # 실행 중인 run: status=running, CallEvent 없음(persist_results 전),
        # 다만 CallFlowDiagram은 이미 있다고 가정(진행 중 폴링마다 upsert되므로
        # 실제로도 존재하는 게 정상 — 없으면 call-flow 자체가 404).
        db.add(TestRun(id=run_id, test_case_id=test_case_id, status=TestRunStatus.RUNNING))
        db.add(CallFlowDiagram(run_id=run_id, mermaid_source="sequenceDiagram\n    participant VCSM as VCSM\n"))
        db.commit()
        assert db.execute(select(CallEvent).where(CallEvent.run_id == run_id)).first() is None
    finally:
        db.close()

    events_resp = await client.get(f"/api/test-runs/{run_id}/events")
    assert events_resp.status_code == 200
    events_body = events_resp.json()
    assert events_body["total"] > 0
    assert all(item["id"] for item in events_body["items"])  # 즉석 파싱본도 id가 채워져 있어야 함
    assert any(item["parsed_type"] == "SIP_INVITE" for item in events_body["items"])

    call_flow_resp = await client.get(f"/api/test-runs/{run_id}/call-flow")
    assert call_flow_resp.status_code == 200
    messages = call_flow_resp.json()["messages"]
    assert len(messages) > 0
    assert messages[0]["source"] == "vcsm_log"
