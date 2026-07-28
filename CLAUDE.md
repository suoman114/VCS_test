# VCS 호처리 시험 자동화 프로그램 — 오케스트레이션 마스터 문서

이 문서는 본 저장소에서 작업하는 **모든 Claude Code 에이전트(오케스트레이터 + 서브에이전트)** 가 가장 먼저 읽어야 하는 설계/운영 문서다.
개별 서브에이전트 정의는 `.claude/agents/*.md`에 있으며, 각 서브에이전트 파일은 이 문서를 전제로 자신의 담당 영역만 상세히 다룬다.

---

## 1. 프로젝트 개요

**목적**: 녹취서버(VCS, Voice/Call Recording Server)의 호처리 시험(VoLTE / McPTT)을 자동화하고, 시험 결과·로그·Call Flow를 시험 케이스 단위로 관리하는 통합 대시보드를 제공한다.

**1차 개발 범위 (Phase 1, MVP)**
- VoLTE 기본 호처리 시험 자동화
- McPTT 기본 호처리 시험 자동화 (SIPp 기반)
- 시험 케이스(Test Case) 등록/관리
- 시험 중 실시간 로그 확인
- 로그 기반 Call Flow 자동 시각화
- 통합 대시보드 (시험 실행/모니터링/이력 조회)

**향후 확장 범위 (Phase 2+, 지금은 설계에서 자리만 예약)**
- 성능(Performance) 시험 — 동시 호 부하, 처리량, 지연 측정
- Abnormal 시험 — 비정상 시나리오(타임아웃, 메시지 누락/순서바뀜, 리소스 고갈 등)
- 기타 시험 유형 확장

> 신규 시험 유형은 항상 "시험 유형 플러그인"으로 추가한다 (§7 참고). 기존 VoLTE/McPTT 코드를 건드리지 않고 확장 가능해야 한다.

---

## 2. 도메인 용어 정리

| 용어 | 설명 |
|---|---|
| VCS | 녹취서버(Voice/Call Recording Server). 통화 신호/음성을 녹취하는 시험 대상 장비. 본 프로그램의 SUT(System Under Test)의 일부. |
| 호처리 (Call Processing) | 통화 발신~응답~종료까지의 시그널링 처리 흐름. |
| VoLTE | LTE망의 음성 통화(IMS/SIP 기반). |
| McPTT | Mission Critical Push-To-Talk. 공공안전망 그룹통신 서비스(3GPP 기반, SIP + MCPTT 애플리케이션 프로토콜). |
| vctp | VCS 내부에서 호처리를 담당하는 프로세스(추정: Voice Call Trunk/Transfer Process류). 설정 파일 적용 후 재기동하면 새 설정으로 호처리 시험이 진행됨. |
| SIPp | 오픈소스 SIP 트래픽 생성/시험 도구. McPTT 호 발생에 사용. XML 시나리오 기반으로 SIP 메시지 흐름을 정의. |
| 기본 호처리 시험 | 정상적인 발신-응답-통화-종료 흐름이 규격대로 동작하는지 확인하는 가장 기본적인 시험 유형. |
| Call Flow | 시험 1회 실행(Test Run) 동안 오간 시그널링 메시지의 순서를 시각화한 시퀀스 다이어그램. |
| Test Case | 재사용 가능한 시험 정의(프로토콜, 대상 설정/시나리오, 판정 기준 포함). |
| Test Run | Test Case를 1회 실행한 인스턴스(로그, 결과, Call Flow가 귀속되는 단위). |

---

## 3. 시험 실행 방식 (핵심 도메인 로직)

### 3.1 VoLTE 기본 호처리 시험
1. Test Case에 연결된 설정 파일을 VCS 서버의 지정 경로에 적용(SCP/SFTP 전송)
2. SSH로 VCS에 접속하여 `vctp` 프로세스 재기동 명령 실행
3. 재기동 직후부터 VCS의 관련 로그 파일/경로를 실시간 tail로 수집 시작
4. 호처리 완료(성공/실패/타임아웃) 판정 기준에 도달할 때까지 수집
5. 수집 종료 → 원본 로그 저장 → 파싱 → Call Flow 생성 → Pass/Fail 판정 → 대시보드에 결과 반영

> **미확정(TBD)**: 설정 파일의 정확한 목적지 경로, `vctp` 재기동 명령(`systemctl` / 커스텀 스크립트 / 시그널 등), 재기동 후 시험이 "완료"되었다고 판단하는 기준(로그 패턴 또는 고정 대기시간). 실제 로그 샘플과 VCS 접근 정보를 받는 즉시 확정한다. 그 전까지 Backend Agent는 이 구간을 인터페이스(어댑터)로 추상화해서 구현한다.

### 3.2 McPTT 기본 호처리 시험
1. Test Case에 연결된 SIPp 시나리오(XML) + 파라미터(대상 IP/Port, 호 수, 호 발생율 등) 로드
2. SIPp 프로세스 실행 (McPTT 호 발생)
3. SIPp 실행과 동시에 VCS 측 로그도 실시간 수집 시작 (SSH tail)
4. SIPp 자체 로그/통계(csv, 스크린 로그)와 VCS 로그를 **Call-ID / 타임스탬프 기준으로 상관관계 매칭**
5. 두 로그 소스를 병합하여 하나의 Call Flow로 재구성
6. Pass/Fail 판정 → 결과 저장 → 대시보드 반영

> **미확정(TBD)**: SIPp 실행 위치(자동화 서버 로컬 vs 별도 SIPp 전용 호스트에 SSH로 원격 실행), McPTT 고유 애플리케이션 메시지(SIP 위에 얹히는 MCPTT 제어 메시지)의 파싱 규칙.

### 3.3 공통 실행 원칙
- 모든 시험 실행은 **비동기 Job**으로 처리하고 Test Run 레코드를 즉시 생성한다(상태: `pending → running → parsing → done/failed/error`).
- 실시간 로그는 수집되는 즉시 WebSocket으로 대시보드에 스트리밍한다 (저장과 스트리밍을 동시에, 수집 완료를 기다리지 않음).
- 원본 로그는 반드시 파일로 보존한다 (`storage/logs/{test_case_id}/{run_id}/...`). 파싱 결과는 별도로 DB에 저장하고, 원본은 재파싱을 위해 남긴다.
- SSH 자격증명/호스트 정보는 코드에 하드코딩하지 않고 환경변수/시크릿 스토어로 관리한다.

---

## 4. 시스템 아키텍처

```
┌──────────────┐     WebSocket(실시간 로그/상태)      ┌──────────────────┐
│  React 대시보드 │ <───────────────────────────────── │   FastAPI 백엔드    │
│ (Test Case/실행/ │ ─────────────────────────────────> │ (API + 오케스트레이션) │
│  로그/CallFlow) │        REST API(CRUD, 실행 트리거)    └──────────┬────────┘
└──────────────┘                                              │
                                                                │ SSH / SCP / subprocess
                                             ┌──────────────────┼───────────────────┐
                                             ▼                  ▼                   ▼
                                       ┌───────────┐     ┌────────────┐     ┌──────────────┐
                                       │ VCS 서버    │     │ SIPp 실행    │     │  로그 저장소    │
                                       │(vctp 재기동, │     │ (McPTT 호   │     │ (파일시스템 +   │
                                       │ 로그 tail)  │     │  발생)      │     │  DB 파싱결과)  │
                                       └───────────┘     └────────────┘     └──────────────┘
```

**기술 스택**
- Backend: Python 3.11+, FastAPI, `asyncssh`(SSH/SFTP 비동기 처리), WebSocket(FastAPI 내장), SQLAlchemy + Alembic
- DB: SQLite로 시작(파일 기반, 설치 부담 없음) → 운영 확장 시 PostgreSQL로 전환 가능하게 SQLAlchemy 추상화 유지
- 백그라운드 Job: 초기엔 `asyncio.create_task` 기반 자체 Job Runner. 동시 실행 시험이 늘어나면 Celery/Redis 큐로 교체 가능하도록 Job Runner를 인터페이스로 분리
- Frontend: React + TypeScript, Vite, 상태관리는 Zustand(가볍게), 차트/그래프는 필요 최소한으로
- Call Flow 시각화: **Mermaid `sequenceDiagram`** 텍스트를 백엔드에서 생성 → 프론트에서 렌더링 (별도 다이어그램 엔진 개발 불필요, 텍스트 기반이라 토큰/저장 비용도 낮음)
- 로그 수집: SSH 기반 실시간 tail(`tail -f` 원격 실행 스트림 또는 파일 polling), 향후 syslog 수신기로 확장 가능하게 어댑터 분리

---

## 5. 디렉토리 구조

```
VCS_test/
├── CLAUDE.md                      # 본 문서
├── README.md
├── .claude/agents/                # 서브에이전트 정의
├── backend/
│   └── app/
│       ├── api/                   # FastAPI 라우터 (REST + WebSocket)
│       ├── core/                  # 설정, 보안/시크릿 로딩
│       ├── models/                # SQLAlchemy 모델 (TestCase, TestRun, CallEvent ...)
│       ├── schemas/                # Pydantic 스키마
│       ├── services/
│       │   ├── volte/             # VoLTE 시험 실행 로직 (파일적용 + vctp 재기동)
│       │   ├── mcptt/             # McPTT 시험 실행 로직 (SIPp 트리거)
│       │   ├── ssh_connector/     # SSH/SCP 공통 클라이언트
│       │   ├── log_collector/     # 실시간 로그 수집 (tail/streaming)
│       │   ├── log_parser/        # 로그 파싱 어댑터/상태머신
│       │   └── callflow/          # 파싱 결과 → Mermaid sequenceDiagram 변환
│       ├── ws/                    # WebSocket 매니저 (실시간 로그/상태 브로드캐스트)
│       └── job_runner/            # 비동기 시험 실행 Job 관리
│   └── tests/
├── frontend/
│   └── src/
│       ├── pages/                 # Dashboard, TestCases, Execution, CallFlow, History
│       ├── components/
│       ├── api/                   # 백엔드 API 클라이언트
│       └── store/
├── testcases/                     # Test Case 정의 (YAML, git으로 버전관리)
│   ├── volte/
│   └── mcptt/
├── scenarios/sipp/                # McPTT용 SIPp XML 시나리오
├── docs/
│   └── log_samples/                # 사용자가 첨부할 실제 VCS/vctp/SIPp 로그 샘플 보관 위치
└── storage/                        # (gitignore) 실행 시 원본 로그/런타임 산출물
    └── logs/{test_case_id}/{run_id}/
```

> **로그 샘플을 주실 때**: `docs/log_samples/` 아래에 프로토콜별(`volte/`, `mcptt/`)로 넣어주시면 Log Parser Agent가 바로 분석해서 파서를 구현한다.

---

## 6. 데이터 모델 (초안)

- **TestCase**: `id, name, category(volte|mcptt), test_type(basic_call|performance|abnormal, 현재는 basic_call만), config_ref(VoLTE 설정파일 경로 or McPTT SIPp 시나리오 경로+파라미터), pass_criteria, created_at, updated_at`
- **TestRun**: `id, test_case_id, status(pending|running|parsing|passed|failed|error), started_at, ended_at, target_host, raw_log_path, result_summary`
- **CallEvent**: `id, run_id, ts, source(vcs_log|sipp_log), raw_line, parsed_type(예: SIP_INVITE, SIP_200OK, VCTP_XXX), seq_no`
- **CallFlowDiagram**: `run_id, mermaid_source, generated_at`

세부 컬럼/정규화는 Backend Agent + Log Parser Agent가 실제 로그 포맷 확보 후 확정한다.

---

## 7. 시험 유형 확장 구조 (성능/Abnormal 대비)

Phase 1에서부터 아래 원칙을 지켜서, 나중에 성능/Abnormal 시험을 **기존 코드 수정 없이 추가**할 수 있게 한다.

- `TestCase.test_type`으로 시험 유형을 구분하고, 유형별 실행기(Executor)는 공통 인터페이스(`TestExecutor.run(test_case) -> TestRun`)를 구현하는 별도 클래스/모듈로 분리한다.
- `services/volte`, `services/mcptt` 는 "프로토콜"이고, "시험 유형(기본호처리/성능/abnormal)"은 별도 축이다. 예: 성능 시험도 VoLTE/McPTT 양쪽에 적용될 수 있으므로, 실행기는 `(protocol, test_type)` 조합으로 조회한다.
- 대시보드/DB 스키마도 `test_type` 필드로 필터링만 하면 새 유형이 그대로 노출되도록 설계한다.

---

## 8. 대시보드 기능 명세 (Phase 1)

1. **시험 케이스 관리**: 목록/등록/수정/삭제, 프로토콜·유형별 필터
2. **시험 실행**: 케이스 선택 후 실행, 실행 중 상태 표시(진행중/완료/실패)
3. **실시간 로그 뷰어**: 실행 중인 Test Run의 로그를 WebSocket으로 실시간 스트리밍 표시 (VCS 로그 / SIPp 로그 탭 구분)
4. **Call Flow 뷰어**: Test Run 종료 후(또는 진행 중 부분적으로) Mermaid 시퀀스 다이어그램 렌더링
5. **시험 이력**: Test Run 목록, Pass/Fail 통계, 과거 로그/Call Flow 재조회
6. **(공통) 연결 상태 표시**: VCS SSH 연결 상태, SIPp 실행 가능 여부 등 헬스체크

---

## 9. 로그 파싱 / Call Flow 생성 설계 원칙

- 로그 포맷은 아직 미확정이므로 **어댑터 패턴**으로 설계한다: `LogAdapter` 인터페이스(원본 라인 → 표준 `CallEvent`) 를 두고, `VctpLogAdapter`, `SippLogAdapter` 등을 구현체로 추가한다. 실제 로그 샘플이 도착하면 정규식/상태머신을 채워 넣는다.
- 파싱은 **항상 결정론적 코드(정규식, 상태머신)로 수행**한다. LLM 에이전트가 원본 로그 전체를 직접 읽고 해석하도록 설계하지 않는다 (§10 Token Guardian 원칙과 직결).
- Call Flow는 파싱된 `CallEvent` 시퀀스를 Mermaid `sequenceDiagram` 텍스트로 변환한다. 참가자(Participant)는 프로토콜에 따라 `UE/SIPp → VCS(vctp)` 등으로 동적 결정.
- 판정(Pass/Fail)은 `pass_criteria`(기대 이벤트 시퀀스, 필수 메시지 존재 여부, 에러 패턴 부재 등)를 파싱 결과와 비교하는 규칙 엔진으로 처리한다.

---

## 10. 에이전트(오케스트레이션) 구성

이 저장소는 **기능 단위로 세분화된 서브에이전트** 체계로 개발한다. 메인 세션(오케스트레이터)이 이 문서를 기준으로 작업을 분해하고, 아래 서브에이전트에게 위임한다. 각 서브에이전트의 상세 지침은 `.claude/agents/`에 있다.

| 에이전트 | 파일 | 담당 |
|---|---|---|
| **Backend Agent** | `backend-agent.md` | FastAPI API, TestRun 오케스트레이션 로직, VoLTE(파일적용+vctp 재기동)/McPTT(SIPp 트리거) 실행기, SSH 커넥터 |
| **Log Collector Agent** | `log-collector-agent.md` | SSH 기반 실시간 로그 수집(tail), 원본 로그 저장, WebSocket 스트리밍 연동 |
| **Log Parser & Call Flow Agent** | `log-parser-callflow-agent.md` | 로그 → CallEvent 파싱 어댑터, Mermaid Call Flow 생성, Pass/Fail 판정 규칙 |
| **Test Case Manager Agent** | `testcase-manager-agent.md` | Test Case 데이터 모델/CRUD API, YAML 정의 스키마, 카테고리/버전 관리 |
| **SIPp Scenario Agent** | `sipp-scenario-agent.md` | McPTT SIPp XML 시나리오 작성/관리, McPTT 고유 메시지 처리 |
| **Frontend/Dashboard Agent** | `frontend-dashboard-agent.md` | React 대시보드 전체 UI(케이스 관리/실행/실시간 로그/Call Flow/이력) |
| **Token Guardian Agent** | `token-guardian-agent.md` | **(필수)** 전체 개발 프로세스의 토큰/컨텍스트 사용을 통제 — 대용량 로그를 에이전트가 직접 읽지 않도록 강제, 컨텍스트 예산 정책 수립·감사, 에이전트 간 핸드오프 시 요약 전달 규칙 관리 |
| **QA/Integration Agent** | `qa-agent.md` | 백엔드/프론트 통합 테스트, 시험 실행 플로우 검증, 회귀 방지 |

### 10.1 오케스트레이터(메인 세션) 원칙
- 작업을 서브에이전트에게 위임할 때, 이 CLAUDE.md와 해당 서브에이전트 파일에 이미 있는 내용을 반복 설명하지 말고 **구체적 작업 범위(파일 경로, 이번에 할 일, 완료 기준)** 만 전달한다.
- 여러 에이전트가 동시에 작업 가능한 독립적 작업(예: Frontend와 Backend API 스펙이 이미 합의된 상태)은 **병렬로 위임**한다.
- 순서 의존성이 있는 작업(예: 데이터 모델 확정 전 API 구현 금지)은 순차 진행한다.
- Test Case Manager Agent가 정의하는 스키마가 Backend/Frontend 모두의 기준이 되므로, 데이터 모델 변경은 반드시 이 에이전트를 거친다.

### 10.2 에이전트 간 핸드오프 규칙 (Token Guardian과 연계)
- 에이전트는 다른 에이전트의 산출물을 참조할 때 **원본 전체가 아니라 요약/스키마/인터페이스만** 전달받는다.
- 대용량 로그 파일, 긴 실행 결과는 파일 경로만 공유하고, 필요한 경우 파싱된 요약(JSON)만 컨텍스트에 올린다.
- 각 에이전트는 작업 완료 시 "무엇을 했는지 + 어떤 인터페이스를 다른 에이전트가 쓸 수 있는지"를 간결히 보고한다. 구현 세부사항 전체를 다시 설명하지 않는다.

---

## 11. 개발 로드맵

- **Phase 1 (현재)**: VoLTE/McPTT 기본 호처리 자동화 + Test Case 관리 + 실시간 로그 + Call Flow + 대시보드 MVP
- **Phase 2**: 성능 시험(동시 호, 처리량/지연 측정, 부하 프로파일)
- **Phase 3**: Abnormal 시험(비정상 시나리오 라이브러리)
- **Phase 4**: 리포트 자동 생성, 알림(실패 시 통보), 다중 VCS 대상 확장 등

---

## 12. 코딩/품질 컨벤션

- Backend: type hint 필수, Pydantic으로 API 경계 검증, 비즈니스 로직은 `services/`에만, 라우터는 얇게 유지
- 로그 파서는 반드시 단위 테스트와 함께 작성 (실제 로그 샘플 fixture 사용)
- 프론트: 컴포넌트는 기능별 폴더링, API 호출은 `api/` 클라이언트로만 수행(컴포넌트에서 직접 fetch 금지)
- 커밋은 기능 단위로 작게, 커밋 메시지에 어떤 에이전트/영역 작업인지 명시 권장

---

## 13. 미확정 사항 (TBD) — 확인되는 대로 이 문서를 갱신

- [ ] VoLTE 설정 파일의 VCS 내 목적지 경로, `vctp` 재기동 정확한 명령/권한
- [ ] 시험 "완료" 판정 기준(로그 패턴 vs 고정 대기시간)
- [ ] SIPp 실행 위치(로컬 vs 원격 SSH) 및 실행 파라미터 표준
- [ ] 실제 VCS/vctp/SIPp 로그 포맷 샘플 (→ `docs/log_samples/`에 첨부 예정)
- [ ] VCS SSH 접속 정보/인증 방식(키 vs 패스워드), 접근 가능한 네트워크 환경
- [ ] Pass/Fail 판정 세부 기준(케이스별 상이할 수 있음)

로그 샘플이 도착하면 Log Parser & Call Flow Agent가 우선적으로 분석하고, 필요 시 이 문서의 §3, §6, §9를 갱신한다.
