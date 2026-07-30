"""Test Run 실행 트리거 + 조회 + 실시간 스트리밍 API (CLAUDE.md §3, §8).

라우터는 얇게 유지한다: 실행 로직은 `app.services.{volte,mcptt}.executor` +
`app.job_runner`가, 실시간 스트리밍은 `app.ws.manager`가 담당한다.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
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
import app.services.mcptt.performance_executor  # noqa: F401
import app.services.volte.executor  # noqa: F401
from app.schemas.test_run import (
    CallEventListResponse,
    CallEventRead,
    CallFlowMessageRead,
    CallFlowRead,
    CallIdListResponse,
    ConcurrencyPoint,
    ReportStatsResponse,
    SetupTimeStats,
    TestRunListResponse,
    TestRunRead,
    TestRunStatsBucket,
    TestRunStatsResponse,
)
from app.services.callflow.generator import detect_protocol, generate_call_flow
from app.services.execution_common import ADAPTERS_BY_LOG_NAME, parse_collected_logs
from app.services.executor_base import executor_registry
from app.services.report_stats import compute_call_setup_time_stats, compute_concurrency_time_series
from app.ws.manager import manager

router = APIRouter(tags=["test-runs"])

STATS_RECENT_DAYS = 7
_IN_PROGRESS_STATUSES = (TestRunStatus.PENDING, TestRunStatus.RUNNING, TestRunStatus.PARSING)


def _stats_bucket_from_counts(counts: dict[TestRunStatus, int]) -> TestRunStatsBucket:
    """상태별 개수 -> `TestRunStatsBucket`. `pass_rate`는 종료된 실행
    (done/failed/error) 기준으로만 계산한다 — 대기/실행 중인 run을 분모에
    넣으면 시험이 몰리는 시점에 실제와 무관하게 Pass율이 출렁인다."""
    passed = counts.get(TestRunStatus.DONE, 0)
    failed = counts.get(TestRunStatus.FAILED, 0)
    error = counts.get(TestRunStatus.ERROR, 0)
    in_progress = sum(counts.get(s, 0) for s in _IN_PROGRESS_STATUSES)
    finished = passed + failed + error
    return TestRunStatsBucket(
        total=finished + in_progress,
        passed=passed,
        failed=failed,
        error=error,
        in_progress=in_progress,
        pass_rate=(passed / finished) if finished else None,
    )


def _get_test_run_or_404(db: Session, run_id: str) -> TestRun:
    test_run = db.get(TestRun, run_id)
    if test_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TestRun not found")
    return test_run


def _test_case_name_map(db: Session, test_case_ids: set[str]) -> dict[str, str]:
    """대시보드/이력/실행 화면에 UUID만 보이던 문제(2026-07-30 UI 개선 요청) —
    TestRun 응답에 test_case_name을 함께 내려주기 위한 일괄 조회. 목록
    엔드포인트에서 N+1 쿼리를 피하려고 test_case_id 집합을 한 번에 IN 조회한다."""
    if not test_case_ids:
        return {}
    rows = db.execute(select(TestCase.id, TestCase.name).where(TestCase.id.in_(test_case_ids))).all()
    return dict(rows)


def _to_test_run_read(run: TestRun, test_case_name: str | None) -> TestRunRead:
    return TestRunRead.model_validate(run).model_copy(update={"test_case_name": test_case_name})


def _load_events(db: Session, test_run: TestRun) -> list[CallEvent]:
    """이 run의 CallEvent를 반환한다 — DB에 있으면 DB에서, 없으면(실행 중이라
    아직 `persist_results`가 한 번도 안 돈 경우) 현재까지 수집된 원본 로그
    파일을 그 자리에서 파싱해 대체한다.

    `CallEvent`는 실행이 완전히 끝나야만 한 번에 DB로 확정 저장된다
    (`execution_common.persist_results` — 폴링마다 재저장하면 중복이 생기기
    때문). 그래서 실행 도중에는 "과거 로그"/클릭-투-로그가 항상 빈 결과만
    받았다(실 서버에서 확인된 문제). 이 함수가 그 간극을 메운다: DB가
    비어있으면 `storage/logs/{test_case_id}/{run_id}/*.log`를
    `parse_collected_logs`로 즉석 파싱해서 돌려준다(같은 파서를 실행기
    폴링 루프가 쓰는 것과 동일하게 재사용 — 파싱 로직 중복 없음).

    즉석 파싱된 이벤트는 DB에 없으므로 `id`가 없다(SQLAlchemy 컬럼 default는
    flush 시점에만 적용됨) — 프론트 캐시 키 안정성을 위해 결정론적 id를
    직접 부여한다.
    """
    events = (
        db.execute(select(CallEvent).where(CallEvent.run_id == test_run.id).order_by(CallEvent.seq_no.asc()))
        .scalars()
        .all()
    )
    if events:
        return list(events)

    settings = get_settings()
    run_dir = settings.log_storage_path / test_run.test_case_id / test_run.id
    if not run_dir.exists():
        return []
    log_names = sorted(p.stem for p in run_dir.glob("*.log") if p.stem in ADAPTERS_BY_LOG_NAME)
    live_events = parse_collected_logs(run_dir, log_names, test_run.id)
    for e in live_events:
        e.id = f"{test_run.id}:{e.source.value}:{e.seq_no}"
    return live_events


@router.post(
    "/test-cases/{test_case_id}/run",
    response_model=TestRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_test_run(test_case_id: str, db: Session = Depends(get_db)) -> TestRunRead:
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

    return _to_test_run_read(test_run, test_case.name)


@router.post(
    "/test-runs/{run_id}/cancel",
    response_model=TestRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_test_run(run_id: str, db: Session = Depends(get_db)) -> TestRunRead:
    """실행 중인 Test Run을 종료한다 — 특히 McPTT 성능 시험처럼 `-m`(총 호 수)
    없이 무기한 실행되는 시험은 이 엔드포인트가 유일한 정상 종료 경로다
    (2026-07-30 요청, `McpttPerformanceExecutor`).

    `job_runner.cancel()`이 해당 run_id의 asyncio.Task를 취소한다 — 실행기가
    그 취소를 잡아 원격 프로세스를 실제로 종료하고 지금까지 수집된 로그로
    최종 결과를 정리하는 건 각 Executor의 책임이다(`McpttPerformanceExecutor.
    run()`은 취소를 흡수해 DONE으로 정상 마무리한다 — 사용자가 종료한 건
    실패가 아니다). 상태 갱신은 비동기로 이루어지므로, 이 응답의 `status`는
    아직 "running"일 수 있다 — 202 Accepted가 그 뜻이고, 클라이언트는
    `GET /test-runs/{run_id}`를 다시 폴링해서 최종 상태를 확인해야 한다.
    """
    test_run = _get_test_run_or_404(db, run_id)
    if test_run.status not in (TestRunStatus.PENDING, TestRunStatus.RUNNING, TestRunStatus.PARSING):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"TestRun {run_id!r}은 이미 종료된 상태({test_run.status.value})라 취소할 수 없다",
        )
    cancelled = await job_runner.cancel(run_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"TestRun {run_id!r}에 대한 실행 중인 job을 찾지 못했다(이미 종료됐을 수 있음)",
        )
    test_case = db.get(TestCase, test_run.test_case_id)
    return _to_test_run_read(test_run, test_case.name if test_case else None)


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
    name_map = _test_case_name_map(db, {run.test_case_id for run in items})
    return TestRunListResponse(
        items=[_to_test_run_read(run, name_map.get(run.test_case_id)) for run in items], total=total
    )


@router.get("/test-runs/stats", response_model=TestRunStatsResponse)
def get_test_run_stats(db: Session = Depends(get_db)) -> TestRunStatsResponse:
    """대시보드 통계 카드용 집계 — 전체/프로토콜(VoLTE·McPTT)별/최근 N일 Pass율.

    **라우트 등록 순서 주의**: `/test-runs/{run_id}`보다 반드시 먼저 등록해야
    한다 — 그렇지 않으면 `GET /test-runs/stats`가 `run_id="stats"`로 해석돼
    `get_test_run`(404)로 새어나간다(FastAPI/Starlette는 라우트를 등록 순서로
    매칭).

    Test Run 개수가 대시보드에서 매번 원본을 다시 훑어야 할 만큼 큰
    데이터셋이 아니라서, DB에 GROUP BY로 집계 카운트만 요청하고 Python에서
    버킷으로 재조합한다 — 원본 로그/CallEvent는 전혀 읽지 않는다
    (token-guardian-agent 원칙).
    """
    rows = db.execute(
        select(TestCase.category, TestRun.status, func.count())
        .select_from(TestRun)
        .join(TestCase, TestRun.test_case_id == TestCase.id)
        .group_by(TestCase.category, TestRun.status)
    ).all()

    overall_counts: dict[TestRunStatus, int] = defaultdict(int)
    by_category_counts: dict[str, dict[TestRunStatus, int]] = defaultdict(lambda: defaultdict(int))
    for category, run_status, count in rows:
        overall_counts[run_status] += count
        by_category_counts[category.value][run_status] += count

    cutoff = datetime.now(timezone.utc) - timedelta(days=STATS_RECENT_DAYS)
    recent_rows = db.execute(
        select(TestRun.status, func.count()).where(TestRun.created_at >= cutoff).group_by(TestRun.status)
    ).all()
    recent_counts: dict[TestRunStatus, int] = dict(recent_rows)

    return TestRunStatsResponse(
        overall=_stats_bucket_from_counts(overall_counts),
        by_category={cat: _stats_bucket_from_counts(counts) for cat, counts in by_category_counts.items()},
        recent=_stats_bucket_from_counts(recent_counts),
        recent_days=STATS_RECENT_DAYS,
    )


@router.get("/test-runs/{run_id}", response_model=TestRunRead)
def get_test_run(run_id: str, db: Session = Depends(get_db)) -> TestRunRead:
    test_run = _get_test_run_or_404(db, run_id)
    test_case = db.get(TestCase, test_run.test_case_id)
    return _to_test_run_read(test_run, test_case.name if test_case else None)


@router.get("/test-runs/{run_id}/call-flow", response_model=CallFlowRead)
def get_test_run_call_flow(
    run_id: str, call_id: str | None = Query(default=None), db: Session = Depends(get_db)
) -> CallFlowRead:
    """저장된 Mermaid 텍스트 + 메시지별 CallEvent 참조(클릭-투-로그용)를 반환한다.

    `mermaid_source`는 DB에 저장된 값을 그대로 쓰지만(최종 확정 시 명시적
    protocol로 생성된 값이 더 정확하므로), `messages`는 `_load_events()`로
    구한 이벤트에서 다시 계산한다(저장 비용이 낮은 파생 데이터라 DB 스키마를
    늘리지 않았다). 실행 중에는 `_load_events`가 원본 로그를 즉석 파싱해서
    채워주므로, 실행 중에도 클릭-투-로그가 동작한다.

    `call_id` 쿼리 파라미터(2026-07-30 추가, McPTT 성능 시험 요청)를 주면
    그 콜의 이벤트만으로 Mermaid를 즉석에서 다시 생성한다 — 성능 시험처럼
    한 Test Run에 수십~수백 콜이 섞여 있으면 전체를 한 다이어그램에
    합쳐봤자 어느 화살표가 어느 콜인지 구별이 안 돼서 사실상 못 읽는다.
    `protocol`은 (필터링된 콜에는 SIP 이벤트가 없을 수도 있으므로) 항상
    전체 이벤트 기준으로 판별해 명시적으로 넘긴다 — 그렇지 않으면
    `detect_protocol`이 필터링된 부분집합만 보고 엉뚱한 프로토콜로
    새 라벨(VCTP/VCSM 등)을 붙일 수 있다.
    """
    test_run = _get_test_run_or_404(db, run_id)
    diagram = db.execute(
        select(CallFlowDiagram).where(CallFlowDiagram.run_id == run_id)
    ).scalar_one_or_none()
    if diagram is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call flow not generated yet (run may still be in progress)",
        )

    events = list(_load_events(db, test_run))

    if call_id is not None:
        protocol = detect_protocol(events)
        filtered = [e for e in events if e.call_id == call_id]
        if not filtered:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"call_id={call_id!r}에 해당하는 이벤트가 없다"
            )
        mermaid_source, message_index = generate_call_flow(filtered, protocol=protocol)
    else:
        mermaid_source = diagram.mermaid_source
        _, message_index = generate_call_flow(events)

    return CallFlowRead(
        run_id=diagram.run_id,
        mermaid_source=mermaid_source,
        generated_at=diagram.generated_at,
        messages=[
            CallFlowMessageRead(index=m.index, seq_no=m.seq_no, source=m.source, call_id=m.call_id)
            for m in message_index
        ],
    )


@router.get("/test-runs/{run_id}/call-ids", response_model=CallIdListResponse)
def list_test_run_call_ids(run_id: str, db: Session = Depends(get_db)) -> CallIdListResponse:
    """이 Test Run에 등장한 call_id 목록(McPTT 성능 시험의 콜별 Call Flow
    선택 드롭다운용, 2026-07-30 추가). 처음 등장한 순서(seq_no 기준)를
    유지한다 — 시험 진행 순서와 일치해서 알파벳 정렬보다 직관적이다.
    """
    test_run = _get_test_run_or_404(db, run_id)
    events = sorted(_load_events(db, test_run), key=lambda e: e.seq_no)
    seen: dict[str, None] = {}
    for e in events:
        if e.call_id:
            seen[e.call_id] = None
    return CallIdListResponse(items=list(seen.keys()))


@router.get("/test-runs/{run_id}/report-stats", response_model=ReportStatsResponse)
def get_test_run_report_stats(
    run_id: str,
    bucket_seconds: int = Query(default=5, ge=1, le=300),
    db: Session = Depends(get_db),
) -> ReportStatsResponse:
    """리포트용 파생 통계 — 콜 설정 시간 분포 / 시간별 동시 통화 수(2026-07-30
    요청, CLAUDE.md §13 TBD 해소). 계산 비용 때문에 라이브 폴링에는 얹지
    않는다(`app.services.report_stats` 모듈 docstring 참고) — 리포트 화면
    진입 시에만 호출한다.
    """
    test_run = _get_test_run_or_404(db, run_id)
    events = _load_events(db, test_run)
    setup = compute_call_setup_time_stats(events)
    concurrency = compute_concurrency_time_series(events, bucket_seconds=bucket_seconds)
    return ReportStatsResponse(
        setup_time=SetupTimeStats(**setup) if setup else None,
        concurrency_series=[ConcurrencyPoint(**point) for point in concurrency],
        bucket_seconds=bucket_seconds,
    )


@router.get("/test-runs/{run_id}/events", response_model=CallEventListResponse)
def list_test_run_events(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> CallEventListResponse:
    """대용량 대비 페이지네이션 필수 (token-guardian-agent 원칙: 한 응답에 몰아넣지 않음).

    실행 중인 run은 `_load_events()`가 원본 로그를 즉석 파싱한 결과로
    대체한다 — DB에는 실행이 끝나야만 CallEvent가 채워지므로, 그 전까지는
    이 엔드포인트가 항상 빈 목록만 반환해서 "과거 로그"/클릭-투-로그가
    실행 중엔 전혀 동작하지 않는 문제가 있었다(실 서버에서 확인됨).
    """
    test_run = _get_test_run_or_404(db, run_id)
    events = _load_events(db, test_run)
    total = len(events)
    page = events[offset : offset + limit]
    return CallEventListResponse(items=[CallEventRead.model_validate(e) for e in page], total=total)


@router.websocket("/ws/test-runs/{run_id}")
async def test_run_ws(websocket: WebSocket, run_id: str) -> None:
    """실시간 로그/상태 스트리밍 (log-collector-agent가 broadcast_to_run으로 전달)."""
    await manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(run_id, websocket)
