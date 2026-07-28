"""VoLTE 시험 실행기 (설정 파일 SCP 전송 -> SSH로 vctp 재기동 -> 완료 판정).

TODO(다음 웨이브, backend-agent): TestExecutor를 구현하는
`VolteBasicCallExecutor`를 여기 추가하고
`executor_registry.register(protocol="volte", test_type="basic_call")`로
등록한다. ssh_connector.SSHConnector와 job_runner.job_runner를 재사용한다.

CLAUDE.md §13 TBD: 설정 파일 목적지 경로, vctp 재기동 명령, 완료 판정 기준.
"""
