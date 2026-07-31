"""VcmmLogAdapter 단위 테스트 (VoLTE/McPTT 공통 녹취 제어 JSON 어댑터).

실제 `docs/log_samples/{volte,mcptt}/vcmm.log` 두 샘플 모두 검증한다.
"""
from __future__ import annotations

import pytest

from app.services.log_parser import VcmmLogAdapter, read_file_lines
from tests.services.log_parser._samples import MCPTT_VCMM_LOG, VOLTE_VCMM_LOG


@pytest.mark.parametrize("sample_path", [VOLTE_VCMM_LOG, MCPTT_VCMM_LOG])
def test_parses_start_and_stop_lifecycle(sample_path) -> None:
    adapter = VcmmLogAdapter()
    events = list(adapter.parse(read_file_lines(str(sample_path))))

    parsed_types = [e.parsed_type for e in events]
    assert "RECORDING_START_REQ" in parsed_types
    assert "RECORDING_START_RES" in parsed_types
    assert "RECORDING_STOP_REQ" in parsed_types
    assert "RECORDING_STOP_RES" in parsed_types

    start_res = next(e for e in events if e.parsed_type == "RECORDING_START_RES")
    assert start_res.reason_code == 2000
    assert start_res.call_id  # 두 샘플 모두 callId가 채워져 있어야 함

    stop_res = next(e for e in events if e.parsed_type == "RECORDING_STOP_RES")
    assert stop_res.reason_code == 2000


def test_mcptt_sample_has_recording_change_events() -> None:
    adapter = VcmmLogAdapter()
    events = list(adapter.parse(read_file_lines(str(MCPTT_VCMM_LOG))))

    parsed_types = {e.parsed_type for e in events}
    assert "RECORDING_CHANGE_REQ" in parsed_types
    assert "RECORDING_CHANGE_RES" in parsed_types
