# backend

FastAPI 백엔드. 담당 에이전트: `backend-agent`, `log-collector-agent`, `log-parser-callflow-agent`, `testcase-manager-agent`.

디렉토리 구조는 루트 `CLAUDE.md` §5를 따른다. 아직 코드가 없으며, 구현 시작 시 아래 구조로 채워진다.

```
app/
├── api/
├── core/
├── models/
├── schemas/
├── services/
│   ├── volte/
│   ├── mcptt/
│   ├── ssh_connector/
│   ├── log_collector/
│   ├── log_parser/
│   └── callflow/
├── ws/
└── job_runner/
tests/
```
