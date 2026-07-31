"""McPTT 시험 실행기 (SIPp 프로세스 트리거, 파라미터 처리).

`McpttBasicCallExecutor`는 import 시점에
`executor_registry.register(protocol="mcptt", test_type="basic_call")`로
자동 등록된다. SIPp 시나리오 XML 경로는 sipp-scenario-agent가 정의하는
`TestCase.config_ref`에서 받아오기만 하고, 시나리오 내용 자체는 다루지 않는다.

CLAUDE.md §13 TBD: SIPp 실행 위치(로컬 vs 원격 SSH, `executor.py`의
`_run_sipp` 참고), MCPTT 애플리케이션 메시지 파싱 규칙(-> log-parser-callflow-agent 담당).
"""
from app.services.mcptt.executor import McpttBasicCallExecutor  # noqa: F401

__all__ = ["McpttBasicCallExecutor"]
