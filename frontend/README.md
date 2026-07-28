# frontend

React + TypeScript(Vite) 대시보드. 담당 에이전트: `frontend-dashboard-agent`.

디렉토리 구조는 루트 `CLAUDE.md` §5를 따른다.

```
src/
├── pages/        # Dashboard, TestCases, Execution, CallFlow, History
├── components/   # LogViewer, MermaidDiagram, StatusBadge 등 재사용 컴포넌트
├── api/          # REST/WebSocket 클라이언트 (컴포넌트에서 직접 fetch 금지)
└── store/        # Zustand 전역 상태 (실시간 로그 버퍼, 구독 중인 run_id 등)
```

## 실행

```bash
cp .env.example .env   # VITE_API_BASE_URL 조정
npm install
npm run dev            # 개발 서버 (http://localhost:5173)
npm run build           # 프로덕션 빌드 (dist/)
```

## API 연동 상태

- `api/testCases.ts`: TestCase CRUD — testcase-manager-agent 확정 스펙 그대로 연동(CONFIRMED).
- `api/testRuns.ts`, `api/useTestRunSocket.ts`, `api/types.ts`의 TestRun/CallEvent/CallFlow/WebSocket
  관련 타입 및 엔드포인트는 backend-agent가 별도로 구현 중인 **가정된 스펙(ASSUMED)** 이다.
  실제 백엔드 API가 확정되면 이 파일들만 수정하면 되도록 페이지/컴포넌트와 분리되어 있다.
- `api/health.ts`: `/api/health`는 현재 `{"status": "ok"}`만 반환한다(CONFIRMED). VCS SSH/SIPp
  세부 헬스체크 필드는 아직 백엔드에 없어 `HealthResponse` 타입에 optional로만 예약되어 있다.
