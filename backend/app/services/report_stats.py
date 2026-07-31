"""리포트용 파생 통계 — 콜 설정 시간 분포 / 시간별 동시 통화 수 (2026-07-30 추가).

CLAUDE.md §13에 TBD로 남겨뒀던 두 항목의 1차 구현.

`performance_stats.py`의 라이브 집계(McPTT 성능 시험 진행 중 2초 폴링마다
갱신되는 총/성공/실패 개수)와는 분리된 별도 모듈이다 — 이 모듈의 계산은
전체 이벤트를 call_id 기준으로 그룹핑/정렬해야 해서(호출마다 O(n)) 라이브
폴링에 얹으면 장시간 성능 시험에서 누적 비용이 커진다. 그래서 이 모듈은
`GET /test-runs/{id}/report-stats`(리포트 화면 진입 시 1회만 호출)에서만
쓴다.

콜 설정 시간 기준(2026-07-30 사용자 확인): SIP INVITE~200 OK가 아니라
`recording_start_req`~`recording_start_res`(VCMM이 녹취를 실제로 붙이는 데
걸린 시간)로 잰다 — vcmc.log의 SIP 메시지 포맷이 배포마다 달라(format A/B,
§13) 항상 파싱된다는 보장이 없는 반면, vcmm.log는 두 배포 모두 공통이고
Pass/Fail 판정 근거와도 동일한 소스라 더 안정적이다.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.models.call_event import CallEvent

_RECORDING_START_REQ = "RECORDING_START_REQ"
_RECORDING_START_RES = "RECORDING_START_RES"
_RECORDING_STOP_RES = "RECORDING_STOP_RES"

_HISTOGRAM_BINS = 10


def _nearest_rank_percentile(sorted_values: list[float], pct: float) -> float:
    """최근접 순위(nearest-rank) 방식 — 존재하지 않는 값을 보간해서 만들어내지
    않는다(항상 실제 관측값 중 하나를 반환), 표본이 적은 소규모 시험에서도
    의미가 왜곡되지 않게 하기 위함."""
    if not sorted_values:
        return 0.0
    idx = max(0, min(len(sorted_values) - 1, int(round(pct / 100 * len(sorted_values))) - 1))
    return sorted_values[idx]


def compute_call_setup_time_stats(events: Sequence[CallEvent]) -> dict[str, Any] | None:
    """콜별 `recording_start_req` ~ `recording_start_res` 소요시간(ms) 분포.

    같은 call_id에 REQ가 여러 번(재시도 등) 나와도 가장 이른 REQ 하나만
    남기고, 그 뒤에 오는 첫 RES와 짝짓는다. REQ보다 먼저 RES가 온 것처럼
    보이는 페어(음수 소요시간)는 이 콜의 응답이 아닌 것으로 보고 조용히
    버린다 — 데이터 이상치를 통계에 섞지 않기 위함.

    이벤트가 없으면(REQ/RES 짝을 하나도 못 찾으면) None을 반환한다 — 빈
    히스토그램을 굳이 만들지 않고 "데이터 없음"을 명시적으로 표현한다.
    """
    req_by_call: dict[str, datetime] = {}
    setup_ms: list[float] = []
    for event in sorted(events, key=lambda e: e.seq_no):
        if event.call_id is None:
            continue
        if event.parsed_type == _RECORDING_START_REQ:
            req_by_call.setdefault(event.call_id, event.ts)
        elif event.parsed_type == _RECORDING_START_RES and event.call_id in req_by_call:
            req_ts = req_by_call.pop(event.call_id)
            delta_ms = (event.ts - req_ts).total_seconds() * 1000
            if delta_ms >= 0:
                setup_ms.append(delta_ms)

    if not setup_ms:
        return None

    sorted_ms = sorted(setup_ms)
    lo, hi = sorted_ms[0], sorted_ms[-1]
    bin_width = (hi - lo) / _HISTOGRAM_BINS if hi > lo else 1.0
    bin_counts = [0] * _HISTOGRAM_BINS
    for value in sorted_ms:
        idx = min(_HISTOGRAM_BINS - 1, int((value - lo) / bin_width)) if hi > lo else 0
        bin_counts[idx] += 1

    return {
        "count": len(sorted_ms),
        "min_ms": round(sorted_ms[0], 1),
        "avg_ms": round(sum(sorted_ms) / len(sorted_ms), 1),
        "p50_ms": round(_nearest_rank_percentile(sorted_ms, 50), 1),
        "p95_ms": round(_nearest_rank_percentile(sorted_ms, 95), 1),
        "max_ms": round(sorted_ms[-1], 1),
        "histogram": [
            {
                "range_start_ms": round(lo + i * bin_width, 1),
                "range_end_ms": round(lo + (i + 1) * bin_width, 1),
                "count": count,
            }
            for i, count in enumerate(bin_counts)
        ],
    }


def compute_concurrency_time_series(
    events: Sequence[CallEvent], *, bucket_seconds: int = 5
) -> list[dict[str, Any]]:
    """`bucket_seconds`(기본 5초, 2026-07-30 사용자 확인) 단위로 "그 구간에
    진행 중이던 콜 수"를 집계한다.

    콜의 시작은 `recording_start_res`(녹취가 실제로 붙은 시점), 종료는
    `recording_stop_res`다. 종료 이벤트가 아직 없는 콜(시험이 도중에
    취소됐거나 아직 진행 중)은 이 run의 마지막 이벤트 시각까지 살아있는
    것으로 간주한다 — 그래야 취소된 시험도 그래프가 중간에 끊기지 않고
    끝까지 그려진다.
    """
    start_by_call: dict[str, datetime] = {}
    stop_by_call: dict[str, datetime] = {}
    for event in events:
        if event.call_id is None:
            continue
        if event.parsed_type == _RECORDING_START_RES:
            start_by_call.setdefault(event.call_id, event.ts)
        elif event.parsed_type == _RECORDING_STOP_RES:
            stop_by_call[event.call_id] = event.ts

    if not start_by_call:
        return []

    all_ts = [event.ts for event in events]
    run_start = min(start_by_call.values())
    run_end = max([*stop_by_call.values(), *all_ts])

    intervals = [(start_by_call[call_id], stop_by_call.get(call_id, run_end)) for call_id in start_by_call]

    total_seconds = max((run_end - run_start).total_seconds(), 0.0)
    bucket_count = int(total_seconds // bucket_seconds) + 1
    run_start_epoch = run_start.timestamp()

    series: list[dict[str, Any]] = []
    for i in range(bucket_count):
        bucket_start = run_start_epoch + i * bucket_seconds
        bucket_end = bucket_start + bucket_seconds
        concurrent = sum(
            1 for start, stop in intervals if start.timestamp() < bucket_end and stop.timestamp() >= bucket_start
        )
        series.append({"offset_sec": i * bucket_seconds, "concurrent_calls": concurrent})

    return series
