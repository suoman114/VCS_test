"""VoLTE 시험 실행기 (설정 파일 SCP 전송 -> SSH로 vctp 재기동 -> 완료 판정).

`VolteBasicCallExecutor`는 import 시점에
`executor_registry.register(protocol="volte", test_type="basic_call")`로
자동 등록된다. 다른 에이전트는 보통 이 모듈을 직접 쓰지 않고
`app.services.executor_base.executor_registry`를 통해 조회한다.

CLAUDE.md §13 TBD: 설정 파일 목적지 경로, vctp 재기동 명령, 완료 판정 기준은
전부 `TestCase.protocol_params`로 주입받는다 (executor.py 모듈 docstring
참고, 하드코딩하지 않음).
"""
from app.services.volte.executor import VolteBasicCallExecutor  # noqa: F401

__all__ = ["VolteBasicCallExecutor"]
