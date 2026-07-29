"""Test Run 실행 트리거 + 조회 + 실시간 스트리밍 API (CLAUDE.md §3, §8).

라우터는 얇게 유지한다: 실행 로직은 `app.services.{volte,mcptt}.executor` +
`app.job_runner`가, 실시간 스트리밍은 `app.ws.manager`가 담당한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.job_runner import job_runner
from app.models.call_event import CallEvent
from app.models.call_flow import CallFlowDiagram
from app.models.test_case import TestCase
from app.models.test_run import TestRun, TestRunStatus

# VoLTE/McPTT executor 모듈을 import해야 @executor_registry.register 데코레이터가
# 실행되어 레지스트리에 등록된다 (app.main이 아직 이 모듈들을 import하지 않으므로
# 여기서 side-effect import를 명시적으로 한다).
import app.services.mcptt.executor  # noqa: F401
import app.services.volte.executor  # noqa: F401
from app.schemas.test_run import (
    CallEventListResponse,
    CallEventRead,
    CallFlowMessageRead,
    CallFlowRead,
    TestRunListResponse,
    TestRunRead,
)
from app.services.callflow.generator import generate_call_flow
from app.services.executor_base import executor_registry
from app.ws.manager import manager

router = APIRouter(tags=["test-runs"])


def _get_test_run_or_404(db: Session, run_id: str) -> TestRun:
    test_run = db.get(TestRun, run_id)
    if test_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TestRun not found")
    return test_run


@router.post(
    "/test-cases/{test_case_id}/run",
    response_model=TestRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_test_run(test_case_id: str, db: Session = Depends(get_db)) -> TestRun:
    """Test Case를 실행한다.

    TestRun을 `pending` 상태로 즉시 생성해 반환하고, 실제 실행은
    `job_runner.submit()`으로 백그라운드에 위임한다(CLAUDE.md §3.3: 모든
    시험 실행은 비동기 Job으로 처리하고 Test Run 레코드를 즉시 생성).

    이 엔드포인트는 반드시 `async def`여야 한다 — `job_runner.submit()`이
    내부적으로 `asyncio.create_task()`를 호출하는데, sync `def` 엔드포인트는
    FastAPI가 별도 워커 스레드(이벤트 루프 없음)에서 실행하기 때문에
    `RuntimeError: no running event loop`가 발생한다. DB 호출 자체는 동기
    SQLAlchemy Session을 그대로 쓴다(짧은 트랜잭션이라 이벤트 루프 블로킹은
    무시할 수준 — Phase 1 범위에서는 허용, 필요 시 추후 비동기 세션으로 교체).
    """
    test_case = db.get(TestCase, test_case_id)
    if test_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TestCase not found")

    protocol = test_case.category.value
    test_type = test_case.test_type.value
    if not executor_registry.is_registered(protocol, test_type):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"No executor registered for protocol={protocol!r}, test_type={test_type!r}",
        )

    test_run = TestRun(test_case_id=test_case.id, status=TestRunStatus.PENDING)
    db.add(test_run)
    db.commit()
    db.refresh(test_run)

    # db.commit()은 기본적으로(expire_on_commit=True) 세션 내 모든 객체의 속성을
    # 만료시킨다 — test_case는 수정하지 않았지만 예외가 아니다. protocol_params처럼
    # 이 시점까지 한 번도 접근하지 않은 컬럼은 아직 로드되지 않은 채로 남는데,
    # 바로 아래에서 expunge()로 세션에서 분리해버리면 백그라운드 Job이 나중에
    # 그 컬럼에 처음 접근할 때 다시 불러올 세션이 없어 DetachedInstanceError가 난다.
    # expunge 전에 refresh로 강제로 전체 컬럼을 로드해둔다.
    db.refresh(test_case)

    # 백그라운드 Job은 요청 스코프 `db` 세션이 닫힌 뒤 실행되므로, 이미 로드된
    # 컬럼 값만 쓰도록 두 인스턴스를 세션에서 분리(expunge)한다.
    db.expunge(test_case)
    db.expunge(test_run)

    executor = executor_registry.create(protocol, test_type, run_id=test_run.id)
    job_runner.submit(test_run.id, lambda: executor.run(test_case))

    return test_run


@router.get("/test-runs", response_model=TestRunListResponse)
def list_test_runs(
    test_case_id: str | None = Query(default=None),
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> TestRunListResponse:
    stmt = select(TestRun)
    if test_case_id is not None:
        stmt = stmt.where(TestRun.test_case_id == test_case_id)
    if status_ is not None:
        try:
            stmt = stmt.where(TestRun.status == TestRunStatus(status_))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid status: {status_!r}") from exc

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = (
        db.execute(stmt.order_by(TestRun.created_at.desc()).offset(offset).limit(limit)).scalars().all()
    )
    return TestRunListResponse(items=list(items), total=total)


@router.get("/test-runs/{run_id}", response_model=TestRunRead)
def get_test_run(run_id: str, db: Session = Depends(get_db)) -> TestRun:
    return _get_test_run_or_404(db, run_id)


@router.get("/test-runs/{run_id}/call-flow", response_model=CallFlowRead)
def get_test_run_call_flow(run_id: str, db: Session = Depends(get_db)) -> CallFlowRead:
    """저장된 Mermaid 텍스트 + 메시지별 CallEvent 참조(클릭-투-로그용)를 반환한다.

    `mermaid_source`는 DB에 저장된 값을 그대로 쓰지만(최종 확정 시 명시적
    protocol로 생성된 값이 더 정확하므로), `messages`는 `CallEvent` 테이블에서
    다시 계산한다(저장 비용이 낮은 파생 데이터라 DB 스키마를 늘리지 않았다).
    실행이 아직 진행 중이면 `CallEvent`가 최종 확정(persist_results) 전이라
    비어있을 수 있다 — 이 경우 WS의 "call_flow" push가 실시간으로 `messages`를
    채워주므로(실행 중엔 그게 주 경로) 문제되지 않는다.
    """
    _get_test_run_or_404(db, run_id)
    diagram = db.execute(
        select(CallFlowDiagram).where(CallFlowDiagram.run_id == run_id)
    ).scalar_one_or_none()
    if diagram is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call flow not generated yet (run may still be in progress)",
        )

    events = (
        db.execute(select(CallEvent).where(CallEvent.run_id == run_id).order_by(CallEvent.seq_no.asc()))
        .scalars()
        .all()
    )
    _, message_index = generate_call_flow(list(events))

    return CallFlowRead(
        run_id=diagram.run_id,
        mermaid_source=diagram.mermaid_source,
        generated_at=diagram.generated_at,
        messages=[
            CallFlowMessageRead(index=m.index, seq_no=m.seq_no, source=m.source, call_id=m.call_id)
            for m in message_index
        ],
    )


@router.get("/test-runs/{run_id}/events", response_model=CallEventListResponse)
def list_test_run_events(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> CallEventListResponse:
    """대용량 대비 페이지네이션 필수 (token-guardian-agent 원칙: 한 응답에 몰아넣지 않음)."""
    _get_test_run_or_404(db, run_id)
    stmt = select(CallEvent).where(CallEvent.run_id == run_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = (
        db.execute(stmt.order_by(CallEvent.seq_no.asc()).offset(offset).limit(limit)).scalars().all()
    )
    return CallEventListResponse(items=[CallEventRead.model_validate(e) for e in items], total=total)


@router.websocket("/ws/test-runs/{run_id}")
async def test_run_ws(websocket: WebSocket, run_id: str) -> None:
    """실시간 로그/상태 스트리밍 (log-collector-agent가 broadcast_to_run으로 전달)."""
    await manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(run_id, websocket)
