"""`build_mcptt_sim_args()` 단위 테스트 — 기본 호처리(-m)와 성능(-r/-rp) 모드."""
from __future__ import annotations

from pathlib import PurePosixPath

from app.services.mcptt.executor import build_mcptt_sim_args


def test_default_mode_uses_calls_count_flag() -> None:
    argv = build_mcptt_sim_args(
        PurePosixPath("/root/mcptt_sim/basic_call.xml"),
        {"target_ip": "10.0.0.10", "max_calls": 10, "local_ip": "192.168.7.65", "local_port": 5080, "control_port": 6061},
        jar_path="/root/mcptt_sim/utgen-jar-with-dependencies.jar",
    )
    assert " ".join(argv).endswith("-m 10 10.0.0.10:5060")
    assert "-r" not in argv
    assert "-rp" not in argv


def test_call_rate_keyword_switches_to_rate_flags() -> None:
    argv = build_mcptt_sim_args(
        PurePosixPath("/root/mcptt_sim/basic_call.xml"),
        {"target_ip": "10.0.0.10", "local_ip": "192.168.7.65", "local_port": 5080, "control_port": 6061},
        jar_path="/root/mcptt_sim/utgen-jar-with-dependencies.jar",
        call_rate=1,
        rate_period_ms=1000,
    )
    cmd = " ".join(argv)
    assert cmd.endswith("-r 1 -rp 1000 10.0.0.10:5060")
    assert "-m" not in argv


def test_rate_period_ms_defaults_to_1000_when_omitted() -> None:
    argv = build_mcptt_sim_args(
        PurePosixPath("/root/mcptt_sim/basic_call.xml"),
        {"target_ip": "10.0.0.10"},
        jar_path="/root/mcptt_sim/utgen-jar-with-dependencies.jar",
        call_rate=2,
    )
    assert " ".join(argv).endswith("-r 2 -rp 1000 10.0.0.10:5060")


def test_legacy_call_rate_protocol_param_does_not_leak_into_rate_mode() -> None:
    """회귀: build_sipp_args()(real-SIPp local 모드)는 protocol_params["call_rate"]를
    이미 다른 의미(초당 호 수, -r 플래그)로 써왔다. build_mcptt_sim_args가 이
    딕셔너리 키를 몰래 읽어버리면, call_rate 필드만 우연히 갖고 있는 기존
    basic_call Test Case가 의도치 않게 -m 대신 -r/-rp 모드로 샌다 — 반드시
    호출부가 명시적으로 넘긴 call_rate 키워드 인자만 봐야 한다."""
    argv = build_mcptt_sim_args(
        PurePosixPath("/root/mcptt_sim/basic_call.xml"),
        {"target_ip": "10.0.0.10", "max_calls": 10, "call_rate": 1},  # 레거시 필드, rate 모드 아님
        jar_path="/root/mcptt_sim/utgen-jar-with-dependencies.jar",
        # call_rate 키워드 인자는 넘기지 않는다 -> -m 모드 유지돼야 함
    )
    assert " ".join(argv).endswith("-m 10 10.0.0.10:5060")
