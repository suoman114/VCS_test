"""Pass/Fail 판정 규칙 엔진 단위 테스트.

주의(CLAUDE.md §13 TBD): 현재 확보된 샘플은 VoLTE/McPTT 각 성공 케이스
1건뿐이라 Fail 판정 규칙은 "성공 조건 미충족 시 fail" 방어적 로직만
검증한다. 실제 실패 로그가 확보되면 이 테스트를 보강해야 한다.
"""
from __future__ import annotations

from app.services.callflow import evaluate_pass_fail
from app.services.log_parser import (
    VcmcLogAdapter,
    VcmmLogAdapter,
    assign_sequence,
    parse_lines_with_adapter,
    read_file_lines,
)
from tests.services.log_parser._samples import MCPTT_VCMC_LOG, MCPTT_VCMM_LOG, VOLTE_VCMM_LOG


def test_volte_success_sample_passes_default_rule() -> None:
    events = parse_lines_with_adapter(VcmmLogAdapter(), read_file_lines(str(VOLTE_VCMM_LOG)), run_id="r1")
    events = assign_sequence(events)

    result = evaluate_pass_fail(events)

    assert result.passed is True
    assert result.details["recording_success"] is True


def test_mcptt_success_sample_passes_default_rule() -> None:
    events = []
    events += parse_lines_with_adapter(VcmcLogAdapter(), read_file_lines(str(MCPTT_VCMC_LOG)), run_id="r2")
    events += parse_lines_with_adapter(VcmmLogAdapter(), read_file_lines(str(MCPTT_VCMM_LOG)), run_id="r2")
    events = assign_sequence(events)

    result = evaluate_pass_fail(events)

    assert result.passed is True


def test_missing_recording_stop_res_is_fail_candidate() -> None:
    events = parse_lines_with_adapter(VcmmLogAdapter(), read_file_lines(str(VOLTE_VCMM_LOG)), run_id="r1")
    events = assign_sequence(events)
    # recording_stop_res를 인위적으로 제거해 "호가 끝나지 않은/실패한" 상황을 흉내낸다.
    truncated = [e for e in events if e.parsed_type != "RECORDING_STOP_RES"]

    result = evaluate_pass_fail(truncated)

    assert result.passed is False
    assert result.details["recording_success"] is False


def test_required_events_and_forbidden_patterns() -> None:
    events = parse_lines_with_adapter(VcmmLogAdapter(), read_file_lines(str(VOLTE_VCMM_LOG)), run_id="r1")
    events = assign_sequence(events)

    ok = evaluate_pass_fail(
        events,
        pass_criteria={
            "require_recording_success": True,
            "required_events": ["RECORDING_START_REQ", "RECORDING_STOP_RES"],
            "forbidden_patterns": [],
        },
    )
    assert ok.passed is True

    missing_required = evaluate_pass_fail(
        events,
        pass_criteria={"required_events": ["SIP_INVITE"]},  # vcmm.log만으로는 SIP 이벤트가 없음
    )
    assert missing_required.passed is False
    assert missing_required.details["missing_required_events"] == ["SIP_INVITE"]

    forbidden_hit = evaluate_pass_fail(
        events,
        pass_criteria={"forbidden_patterns": ["RECORDING_STOP_RES"]},
    )
    assert forbidden_hit.passed is False
    assert forbidden_hit.details["forbidden_pattern_hits"]
