"""McPTT 성능 시험 결과 요약 통계 (2026-07-30 추가).

`CallEvent` 시퀀스에서 파생하는 1차 집계만 담당한다 — vcmm.log의
`recording_start_res`/`recording_stop_res` `reasonCode`로 성공/실패 콜을
센다(§9.1/§13에서 확인된 성공 판정 근거와 동일한 기준을 쓰기 위해
`app.services.callflow.rules.extract_vcmm_header`를 그대로 재사용한다 —
성공 조건 로직이 기본 호처리 Pass/Fail 판정과 어긋나면 안 되므로).

**범위(1차, 2026-07-30 요청에 대한 검토 결과)**: 총 콜 수/성공/실패 개수,
목표 대비 실제 달성 호 발생률, 진행 중(아직 recording_stop 안 됨) 콜 수
정도의 단순 집계만 제공한다. 콜 설정 시간(setup time) 분포나 시간별
동시 통화 수 그래프 같은 시계열 분석은 CallEvent 테이블만으로도 계산은
가능하지만(타임스탬프 버킷팅), 매 요청마다 전체 이벤트를 다시 훑어야 해
비용이 크고 프론트 시각화까지 고려하면 별도 집계 저장이 필요할 수 있다 —
이번 1차 구현 범위에서는 제외하고 CLAUDE.md TBD로 남긴다(사용자 확인 후
2차로 진행).
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.models.call_event import CallEvent
from app.services.callflow.rules import extract_vcmm_header

_RECORDING_START_RES = "RECORDING_START_RES"
_RECORDING_STOP_RES = "RECORDING_STOP_RES"


def _is_recording_success(event: CallEvent) -> bool:
    header = extract_vcmm_header(event)
    reason_code = header.get("reasonCode") if header else event.reason_code
    reason = header.get("reason") if header else None
    return reason_code == 2000 and reason == "Success"


def compute_mcptt_performance_stats(events: Sequence[CallEvent], *, elapsed_sec: float) -> dict[str, Any]:
    """`TestRun.result_summary`(JSON)에 그대로 병합해 넣을 집계 dict를 만든다.

    `total_calls`는 `recording_start_res`(호 발생이 VCMM에 실제로 접수된
    시점)를 기준으로 센다 — SIP INVITE 자체는 vcmc.log 포맷이 배포마다 달라
    (2026-07-30 확인, `vcmc_adapter.py` 참고) 항상 파싱된다는 보장이 없지만,
    녹취 제어(vcmm.log)는 두 포맷 모두에서 공통으로 쓰는 1차 판정 소스라
    더 안정적이다.
    """
    start_res_events = [e for e in events if e.parsed_type == _RECORDING_START_RES]
    stop_res_events = [e for e in events if e.parsed_type == _RECORDING_STOP_RES]

    started_call_ids = {e.call_id for e in start_res_events if e.call_id}
    completed_call_ids = {e.call_id for e in stop_res_events if e.call_id}
    successful_call_ids = {e.call_id for e in stop_res_events if e.call_id and _is_recording_success(e)}

    total_calls = len(started_call_ids)
    successful_calls = len(successful_call_ids)
    failed_calls = len(completed_call_ids - successful_call_ids)
    in_progress_calls = max(len(started_call_ids - completed_call_ids), 0)
    achieved_call_rate_per_sec = (total_calls / elapsed_sec) if elapsed_sec > 0 else 0.0

    return {
        "total_calls": total_calls,
        "successful_calls": successful_calls,
        "failed_calls": failed_calls,
        "in_progress_calls": in_progress_calls,
        "achieved_call_rate_per_sec": round(achieved_call_rate_per_sec, 3),
    }
