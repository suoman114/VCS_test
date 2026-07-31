"""로그 파싱 어댑터 패키지 (CLAUDE.md §9).

다른 에이전트 사용법::

    from app.services.log_parser import (
        VctpLogAdapter, VcsmLogAdapter, VcmmLogAdapter, VcmcLogAdapter, SippLogAdapter,
        read_file_lines, parse_lines_with_adapter, assign_sequence,
    )

    events = parse_lines_with_adapter(VcsmLogAdapter(), read_file_lines(path), run_id=run.id)
    events += parse_lines_with_adapter(VcmmLogAdapter(), read_file_lines(vcmm_path), run_id=run.id)
    events = assign_sequence(events)  # 여러 소스를 시간순으로 병합 + seq_no 재부여
"""
from app.services.log_parser.base import (  # noqa: F401
    LogAdapter,
    LogLine,
    ParsedEvent,
    assign_sequence,
    build_call_events,
    iter_log_lines,
    parse_lines_with_adapter,
    read_file_lines,
)
from app.services.log_parser.sipp_adapter import SippLogAdapter  # noqa: F401
from app.services.log_parser.vcmc_adapter import VcmcLogAdapter  # noqa: F401
from app.services.log_parser.vcmm_adapter import VcmmLogAdapter  # noqa: F401
from app.services.log_parser.vcsm_adapter import VcsmLogAdapter  # noqa: F401
from app.services.log_parser.vctp_adapter import VctpLogAdapter  # noqa: F401

__all__ = [
    "LogAdapter",
    "LogLine",
    "ParsedEvent",
    "SippLogAdapter",
    "VcmcLogAdapter",
    "VcmmLogAdapter",
    "VcsmLogAdapter",
    "VctpLogAdapter",
    "assign_sequence",
    "build_call_events",
    "iter_log_lines",
    "parse_lines_with_adapter",
    "read_file_lines",
]
