# VCS 호처리 시험 자동화 프로그램

녹취서버(VCS)의 VoLTE / McPTT 기본 호처리 시험을 자동화하고, 시험 케이스별 로그·Call Flow·결과를 통합 대시보드에서 관리하는 프로그램.

## 시작하기 전에

이 저장소는 **Claude Code 오케스트레이션 방식**으로 개발한다. 작업을 시작하기 전에 먼저 [`CLAUDE.md`](./CLAUDE.md)를 읽는다 — 전체 설계, 아키텍처, 도메인 지식, 서브에이전트 구성이 모두 정리되어 있다.

서브에이전트 정의는 [`.claude/agents/`](./.claude/agents)에 있다:

- `backend-agent` — FastAPI 백엔드
- `log-collector-agent` — 실시간 로그 수집
- `log-parser-callflow-agent` — 로그 파싱 / Call Flow 생성
- `testcase-manager-agent` — 시험 케이스 데이터 모델/관리
- `sipp-scenario-agent` — McPTT용 SIPp 시나리오
- `frontend-dashboard-agent` — React 대시보드
- `token-guardian-agent` — 토큰/컨텍스트 사용 통제 (필수)
- `qa-agent` — 통합 테스트

## 현재 상태

Phase 1(VoLTE/McPTT 기본 호처리 MVP) 설계 완료, 구현 시작 전. `CLAUDE.md` §13의 미확정 사항(TBD) 확인 및 `docs/log_samples/`에 실제 로그 샘플 확보가 다음 단계다.
