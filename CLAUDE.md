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
| vctp | VCS 내부에서 네트워크 인터페이스의 패킷을 캡처(pcap)하여 SIP 시그널링은 VCSM으로, 미디어(RTP)는 VCMM으로 릴레이하는 프로세스. `docs/log_samples/volte/vctp.log` 확인 결과 실제 호처리 로직은 없고 패킷 캡처/릴레이만 수행(로그의 99%가 "send RTP message to VCMM" 류). 설정 파일(`/home/vcs/vctp/config/`)에 `SAMPLEHOME`/`SAMPLEFILE1`(예: `imsVideo30sec.pcap`) 항목이 있어, 사전 캡처된 pcap 샘플을 재생(replay)해 호처리를 시뮬레이션하는 것으로 추정됨(§3.1 참고, 최종 확인 필요). |
| VCSM | VCS Signaling Manager(추정 명칭). vctp로부터 SIP 메시지를 전달받아 호 상태(INVITE/ACK/BYE 등)를 처리하고, VCMM에 녹취 시작/종료를 요청하는 VoLTE용 시그널링 처리 프로세스. 로그: `vcsm.log`. |
| VCMM | VCS Media Manager. VCSM(VoLTE) 또는 VCMC(McPTT)로부터 `recording_start_req`/`recording_stop_req`(RabbitMQ, JSON)를 받아 실제 녹취 파일(pcap) 생성/관리를 담당. 응답 메시지의 `reasonCode`/`reason`이 녹취(=호처리) 성공/실패 판정의 핵심 근거. 로그: `vcmm.log`(VoLTE·McPTT 공통 프로세스로 보임). |
| VCMC | VCS MCPTT Controller(추정 명칭). McPTT 시험 샘플에서 VCSM 대신 등장하며, SIP + MCPTT 전용 XML(`mcpttinfo`, multipart/mixed 본문)을 처리. 로그: `vcmc.log`. VoLTE의 vctp/VCSM에 해당하는 프로세스가 McPTT에도 별도로 있는지는 샘플에서 확인되지 않음(TBD). |
| SIPp | 오픈소스 SIP 트래픽 생성/시험 도구. McPTT 호 발생에 사용. XML 시나리오 기반으로 SIP 메시지 흐름을 정의. |
| 기본 호처리 시험 | 정상적인 발신-응답-통화-종료 흐름이 규격대로 동작하는지 확인하는 가장 기본적인 시험 유형. |
| Call Flow | 시험 1회 실행(Test Run) 동안 오간 시그널링 메시지의 순서를 시각화한 시퀀스 다이어그램. |
| Test Case | 재사용 가능한 시험 정의(프로토콜, 대상 설정/시나리오, 판정 기준 포함). |
| Test Run | Test Case를 1회 실행한 인스턴스(로그, 결과, Call Flow가 귀속되는 단위). |

> 위 VCS 내부 프로세스 이름(VCSM/VCMM/VCMC)은 로그의 `msgFrom` 필드와 파일명에서 역추적한 추정 명칭이다. 정확한 공식 명칭/역할은 확인되는 대로 갱신한다.

---

## 3. 시험 실행 방식 (핵심 도메인 로직)

### 3.1 VoLTE 기본 호처리 시험 (2026-07-29 실 환경 확인 후 확정)
1. vctp가 재생(replay)할 pcap 샘플은 이미 VCS의 `/home/vcs/vctp/sample`에 있다. "설정 적용"은 새 파일을 업로드하는 게 아니라, vctp 설정(`/home/vcs/vctp/config/vctp_user.config`)의 `SAMPLEFILE1` 항목을 시험하려는 pcap 파일명으로 SSH `sed` 치환하는 것이다. Test Case 등록 폼은 `GET /api/vcs/volte-sample-files`(SSH `ls`)로 조회한 목록을 select box로 보여준다.
2. SSH로 VCS에 접속하여 `stopmc -b vctp` → `startmc -b vctp` 순서로 vctp를 재기동 → 재기동된 vctp가 pcap을 재생하며 SIP는 VCSM으로, RTP는 VCMM으로 릴레이
3. 재기동 직후부터 VCS의 관련 로그 파일을 실시간 tail로 수집 시작 — 대상은 `vcsm.log`(`/home/vcs/vcsm/logs/vcsm.log`, SIP 시그널링), `vcmm.log`(`/home/vcs/vcmm/logs/vcmm0.log`, 녹취 제어/결과), `vctp.log`(`/home/vcs/vctp/logs/vctp0.log`, 패킷 릴레이). `vctp.log`는 패킷 단위 릴레이 로그가 대부분(§9 참고)이라 Call Flow/판정에서는 여전히 저비중으로 다루지만, 대시보드에 프로세스별 로그 탭(vcsm/vcmm/vctp)을 제공하기 위해 다른 로그와 동일하게 tail 대상에 포함한다(2026-07-29 실 서버 경로 확인).
4. 호처리 완료(성공/실패/타임아웃) 판정 기준에 도달할 때까지 수집 — **확인된 성공 판정 근거**: `vcmm.log`에서 VCMM이 보내는 `recording_stop_res` 메시지의 `header.reasonCode == 2000 && header.reason == "Success"`. SIP 레벨에서는 `vcsm.log`의 BYE ↔ 200 OK 교환과 시점이 일치.
5. 수집 종료 → 원본 로그 저장 → 파싱 → Call Flow 생성 → Pass/Fail 판정 → 대시보드에 결과 반영

구현: `backend/app/services/volte/executor.py`(`VolteBasicCallExecutor`), 샘플 목록 조회는 `backend/app/services/volte/sample_files.py` + `GET /api/vcs/volte-sample-files`. 경로/명령 기본값은 `Settings`(`app/core/config.py`)에 있고 `.env`로 배포 환경마다 override 가능.

> **미확정(TBD)**: 실패/타임아웃 케이스의 실제 로그 패턴(현재 확보한 샘플은 성공 케이스 1건뿐이라 실패 판정 규칙을 아직 못 만든다 — 실패/에러 로그 샘플 추가 필요). `sed` 치환 대상 라인의 정확한 문법(공백 등)은 vctp.log의 파싱된 출력에서 역추정한 것이라 실 서버 최초 실행 시 검증 필요.

### 3.2 McPTT 기본 호처리 시험 (2026-07-29 실 환경 확인 후 확정)
1. Test Case에 연결된 SIPp 시나리오(XML) + 파라미터(대상 IP/Port, 호 수, 호 발생율 등) 로드
2. SIPp는 VCS와 별도인 전용 호스트에서 실행된다(SSH로 시나리오 업로드 → 원격 실행 → SIPp 자체 로그 다운로드, `sipp_exec_mode="ssh"`). VCS측 로그 tail을 SIPp 실행 전에 먼저 시작한다.
3. SIPp 실행과 동시에 VCS 측 로그도 실시간 수집 — 대상은 `vcmc.log`(`/home/vcs/vcmc/logs/vcmc.log`, SIP+MCPTT 시그널링), `vcmm.log`(`/home/vcs/vcmm/logs/vcmm0.log`, 녹취 제어/결과). `docs/log_samples/mcptt/`에서 확인된 VCS 측 프로세스는 이 둘뿐이며(VoLTE의 vctp/vcsm에 대응하는 별도 프로세스가 McPTT에도 있는지는 미확인, TBD), `vcmc.log`는 SIP 메시지 원문(멀티파트 MIME, `application/vnd.3gpp.mcptt-info+xml` 등 MCPTT 전용 바디 포함)을 그대로 담고 있다.
4. SIPp 자체 로그/통계(csv, 스크린 로그)와 VCS 로그를 **Call-ID / 타임스탬프 기준으로 상관관계 매칭**
5. 두 로그 소스를 병합하여 하나의 Call Flow로 재구성
6. Pass/Fail 판정 → 결과 저장 → 대시보드 반영 — **확인된 성공 판정 근거**: VoLTE와 동일하게 `vcmm.log`의 `recording_stop_res`가 `reasonCode == 2000 && reason == "Success"`. McPTT 샘플에는 `recording_change_req/res`(21회, 그룹 통화 중 발언권/플로어 변경으로 추정)가 추가로 존재 — Call Flow에는 표시하되 Pass/Fail 판정에는 필수 아님(추정, 확인 필요).

구현: `backend/app/services/mcptt/executor.py`(`McpttBasicCallExecutor`, 로컬/원격 SIPp 실행 모두 지원).

> **미확정(TBD)**: `recording_change_req/res`의 정확한 의미와 판정 영향 여부, 실패/타임아웃 케이스의 실제 로그 패턴(현재 샘플은 성공 케이스 1건), Call-ID/타임스탬프 기반 SIPp↔VCS 로그 상관관계 매칭(SippLogAdapter는 아직 스텁).

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
- **CallEvent**: `id, run_id, ts, source(vctp_log|vcsm_log|vcmm_log|vcmc_log|sipp_log), raw_line, parsed_type(예: SIP_INVITE, SIP_200OK, RECORDING_START_REQ, RECORDING_STOP_RES), call_id, reason_code, seq_no`
- **CallFlowDiagram**: `run_id, mermaid_source, generated_at`

세부 컬럼/정규화는 Backend Agent + Log Parser Agent가 실제 로그 포맷 확보 후 확정한다. `source`/`parsed_type` 값은 `docs/log_samples/`에서 확인된 실제 프로세스(vctp/vcsm/vcmm, McPTT는 vcmc/vcmm)와 메시지 타입(`recording_start_req`, `recording_start_res`, `recording_stop_req`, `recording_stop_res`, McPTT는 `recording_change_req/res` 추가, SIP 메서드는 INVITE/ACK/BYE/CANCEL/UPDATE/PRACK/NOTIFY/REFER/OPTIONS/MESSAGE)를 기준으로 확정했다.

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
3. **실시간 로그 뷰어**: 실행 중인 Test Run의 로그를 WebSocket으로 실시간 스트리밍 표시. 탭은 채널(VCS/SIPp) 단위가 아니라 **프로세스 단위**(vcsm/vcmc/vcmm/vctp/sipp)로 세분화되며, 해당 Test Run에서 실제로 로그가 들어오는 프로세스만 동적으로 탭이 생긴다(예: VoLTE는 vcsm/vcmm/vctp, McPTT는 vcmc/vcmm).
4. **Call Flow 뷰어**: Test Run 종료 후(또는 진행 중 부분적으로) Mermaid 시퀀스 다이어그램 렌더링. 실행 화면(로그 뷰어) 바로 아래에 함께 표시해 페이지 이동 없이 로그와 Call Flow를 동시에 볼 수 있다(별도 `/call-flow/:runId` 페이지는 이력 조회용으로 유지).
5. **시험 이력**: Test Run 목록, Pass/Fail 통계, 과거 로그/Call Flow 재조회
6. **(공통) 연결 상태 표시**: VCS SSH 연결 상태, SIPp 실행 가능 여부 등 헬스체크

---

## 9. 로그 파싱 / Call Flow 생성 설계 원칙

- **어댑터 패턴**으로 설계한다: `LogAdapter` 인터페이스(원본 라인 → 표준 `CallEvent`)를 두고, 프로세스별로 `VctpLogAdapter`, `VcsmLogAdapter`, `VcmmLogAdapter`, `VcmcLogAdapter`, `SippLogAdapter`를 구현체로 추가한다.
- 파싱은 **항상 결정론적 코드(정규식, 상태머신)로 수행**한다. LLM 에이전트가 원본 로그 전체를 직접 읽고 해석하도록 설계하지 않는다 (§10 Token Guardian 원칙과 직결).
- Call Flow는 파싱된 `CallEvent` 시퀀스를 Mermaid `sequenceDiagram` 텍스트로 변환한다. 참가자(Participant)는 프로토콜에 따라 `UE/SIPp → VCS(vctp)` 등으로 동적 결정.
- 판정(Pass/Fail)은 `pass_criteria`(기대 이벤트 시퀀스, 필수 메시지 존재 여부, 에러 패턴 부재 등)를 파싱 결과와 비교하는 규칙 엔진으로 처리한다.

### 9.1 실제 로그 샘플 기반 확정 사항 (`docs/log_samples/volte/`, `docs/log_samples/mcptt/`)

**공통 라인 그래머** (vctp/vcsm/vcmm/vcmc 4개 프로세스 모두 동일 포맷):
```
[YYYY-MM-DD HH:MM:SS.mmm][LEVEL] [Thread-Name] (callId) (from번호) (to번호) 메시지 텍스트 - (ClassName.java:lineNo)
```
- `callId`/`from`/`to`가 문맥상 없으면 빈 괄호 `()`로 표기된다. 정규식 파서는 이 3개 캡처 그룹을 optional로 다뤄야 한다.
- 일부 메시지는 본문에 **JSON**(RMQ 메시지: `recording_start_req/res`, `recording_stop_req/res`, McPTT는 `recording_change_req/res`)을 포함하고, 일부(vcsm/vcmc)는 본문에 **SIP 메시지 원문 전체**(헤더+SDP 또는 MCPTT용 multipart/mixed 바디)를 포함한다. 어댑터는 라인 하나가 아니라 "블록"(멀티라인) 단위로 파싱해야 하는 경우가 있다.

**프로세스별 파싱 우선순위/특성**:
- `vctp.log`: 표본에서 8972줄 중 8866줄(99%)이 `DumpPacketTask.java:156`("send RTP message to VCMM")류의 패킷 단위 릴레이 로그로 Call Flow 관점에서는 노이즈에 가깝다. 파서는 이 라인들을 **기본적으로 필터링**하고, `DumpPacketTask.java:131`("send SIP message to VCSM", SIP 메서드/상태 포함)만 저비중 참고용으로 취급한다. **SIP 시그널링의 1차 소스는 `vcsm.log`/`vcmc.log`로 삼는다** (vctp 로그는 vcsm/vcmc의 내용과 사실상 중복).
- `vcsm.log` (VoLTE) / `vcmc.log` (McPTT): Call Flow의 핵심 소스. SIP 메시지 원문이 그대로 로그에 있어 `From/To/Call-ID/CSeq` 등 표준 SIP 헤더 파싱이 가능하다.
- `vcmm.log` (VoLTE·McPTT 공통): 녹취 제어 메시지(JSON) 소스. **Pass/Fail 판정의 1차 근거**: `recording_stop_res.header.reasonCode == 2000 && reason == "Success"`. `Duration calculated: HH:MM:SS.mmm` 라인으로 통화 지속시간도 추출 가능.

Log Parser & Call Flow Agent는 위 4개 어댑터부터 구현하고, 실패/타임아웃 케이스 로그가 추가로 확보되면 실패 판정 정규식을 보강한다 (§13 참고).

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

- [x] 실제 VCS 로그 포맷 샘플 — `docs/log_samples/volte/{vctp,vcsm,vcmm}.log`, `docs/log_samples/mcptt/{vcmc,vcmm}.log`로 확보 완료. 라인 그래머·프로세스 역할·성공 판정 기준을 §2, §3, §9에 반영함.
- [x] (부분) 시험 "완료"/Pass 판정 기준 — `vcmm.log`의 `recording_stop_res` 메시지 `reasonCode == 2000 && reason == "Success"`로 확인. **단, 이는 성공 케이스 근거일 뿐, 실패/타임아웃 시 어떤 로그 패턴이 남는지는 아직 미확인.**
- [ ] **실패/에러/타임아웃 케이스의 실제 로그 샘플** — 현재 확보한 샘플은 VoLTE·McPTT 각 1건씩, 전부 성공 케이스다. Pass/Fail 판정 규칙(특히 Fail 쪽)을 완성하려면 실패 사례 로그가 필요.
- [x] "설정 파일 적용 후 vctp 재기동"의 정확한 절차 (2026-07-29 실 환경 확인) — vctp는 이미 `/home/vcs/vctp/sample`에 있는 pcap 샘플 중 하나를 재생한다. "적용"은 vctp 설정(`/home/vcs/vctp/config/vctp_user.config`)의 `SAMPLEFILE1` 항목을 선택된 파일명으로 바꾸는 것이며(SSH `sed`), 파일을 새로 업로드하지 않는다. `VolteBasicCallExecutor`(`backend/app/services/volte/executor.py`)가 이 절차로 재작성됨. Test Case 등록 폼은 `GET /api/vcs/volte-sample-files`로 조회한 목록을 select box로 보여준다.
- [x] `vctp` 재기동 정확한 명령 — `stopmc -b vctp` → `startmc -b vctp` 순차 실행(`Settings.vctp_stop_cmd`/`vctp_start_cmd`, `.env`로 override 가능). 권한(sudo 필요 여부 등)은 실 서버에서 아직 검증 전.
- [ ] McPTT에도 VoLTE의 vctp/vcsm에 대응하는 별도 프로세스가 있는지, 아니면 vcmc가 그 역할까지 겸하는지
- [ ] McPTT `recording_change_req/res`(그룹 발언권/플로어 변경 추정)의 정확한 의미와 Pass/Fail 판정 영향 여부
- [x] SIPp 실행 위치 — VCS와 별도인 전용 SIPp 호스트에서 실행됨(2026-07-29 확인). `sipp_exec_mode="ssh"`로 원격 실행 구현 완료(`McpttBasicCallExecutor._run_sipp_remote`). (2026-07-29 추가) 이 SIPp 호스트는 root 직접 SSH 로그인이 막혀있어(`PermitRootLogin no`) `sysadm` 같은 일반 계정으로 접속한 뒤 `su - root`로 전환해야 한다 — `SSHConnector.run_command_as_su()`(PTY 위에서 `su`의 비밀번호 프롬프트에 직접 응답, `app/services/ssh_connector/client.py`)로 구현했고, `Settings.sipp_ssh_root_password`(또는 대시보드 "설정"의 SIPp su root 비밀번호)가 채워져 있을 때만 이 경로를 타며 비어있으면 기존처럼 로그인 계정 권한으로 직접 실행한다. **(2026-07-30 실 서버 버그 발견 및 수정)** 실 서버에서 `RuntimeError: su - root 인증 실패로 보임`이 발생했는데, 캡처된 출력을 보면 `su - root`는 실제로 성공했다(`Last login:` 배너 + `[root{997} ~ ]` 프롬프트 확인). 원인은 새 root 로그인 쉘의 시작 스크립트(`.bashrc.uasys`)가 이전에 `stty -echo`로 꺼둔 로컬 에코를 다시 켜는 바람에, 우리가 stdin에 쓴 명령 문자열(`whoami; echo __SU_CHECK__:$?`)이 아직 `$?`가 평가되지 않은 글자 그대로 먼저 되읽혔고, 이 echo된 텍스트가 부분 문자열 매칭(`"__SU_CHECK__:" in buf`)에 걸려 "명령 완료"로 오판된 것이었다. 마커를 정규식 `r"__SU_CHECK__:\d"`/`r"__CMD_END__:\d"`(콜론 뒤에 반드시 숫자)로 바꿔, 실제 쉘이 평가한 결과만 매칭되고 echo된 미평가 텍스트는 구조적으로 걸리지 않게 수정(`read_until` in `run_command_as_su`). 실 서버에서 캡처된 것과 정확히 같은 청크 순서/내용을 재현하는 회귀 테스트 추가(`test_run_command_as_su_ignores_echoed_command_text_before_real_output`). 다만 이 fix 자체가 사용자의 실 서버에서 재검증되지는 않았다 — 다음 시험 실행 시 확인 필요.
- [x] **McPTT 실 실행 방식 정정(2026-07-29, 사용자 확인)** — 이전에 "실제 SIPp 바이너리(`/root/SIPP/sipp`)를 원격 실행한다"고 가정했던 건 틀렸다. 실제로는:
  1. SIPp 전용 호스트의 `Settings.mcptt_sim_dir`(기본 `/root/mcptt_sim`)에 시나리오 XML들과 자체 제작 Java 도구(`utgen-jar-with-dependencies.jar`, `Settings.mcptt_sim_jar_name`)가 이미 올라가 있다. 저장소의 `scenarios/sipp/*.xml`을 업로드하는 게 아니라, VoLTE의 pcap 샘플 선택과 동일한 패턴으로 **원격에 이미 있는 파일 중 하나를 select box로 고른다** — `GET /api/vcs/mcptt-scenario-files`(SSH `ls`, `app/services/mcptt/scenario_files.py`)가 `*.xml` 목록을 조회하고, `TestCaseForm.tsx`가 VoLTE 브랜치와 동일한 구조로 select box를 보여준다. 선택된 파일명은 `config_ref`와 `protocol_params.scenario_file` 양쪽에 반영된다(둘 다 동일 값 유지, VoLTE의 `sample_file`과 동일한 관례).
  2. 실행 커맨드도 real SIPp가 아니라 `java -jar utgen-jar-with-dependencies.jar -sf <시나리오> -i <local_ip> -p <local_port> -cp <control_port> -m <calls_count> <target_host>:<target_port>` 형태다(`build_mcptt_sim_args()`). `-r`(call rate)/`-t`(transport)/`-s`/`-key`(MCPTT 전용 SIP 키워드)/`-trace_*`(SIPp 트레이스 로그) 같은 기존 real-SIPp 전용 플래그는 이 도구에 없다.
  3. 이 도구는 SIPp 자체 로그 파일(message/screen/stat)을 만들지 않으므로, 시나리오 업로드도 실행 후 로그 다운로드도 더 이상 하지 않는다(`_run_sipp_remote`가 커맨드 실행 하나만 한다) — **McPTT 시험의 로그 소스는 `vcmc.log`/`vcmm.log`뿐**이며(§3.2와 일치), Call Flow도 VoLTE와 동일한 3-레인 구조(SIPp/UE ↔ VCMC ↔ VCMM, `callflow/generator.py`)를 그대로 쓴다(이 부분은 애초에 vcmc.log의 `isSender` 필드로만 방향을 추론해서 별도 sipp 로그가 필요 없었으므로 변경 없음).
  `sipp_exec_mode: "local"`(개발/테스트 전용, 실 배포엔 안 쓰임) 경로는 기존 real-SIPp 커맨드(`build_sipp_args`)를 그대로 유지한다 — 두 실행 경로가 이제 서로 다른 도구를 쓴다는 점에 유의.
- [x] VCS/SIPp 로그의 실제 경로 확인 — `vcsm.log`(`/home/vcs/vcsm/logs/vcsm.log`), `vcmm.log`(`/home/vcs/vcmm/logs/vcmm0.log`), `vcmc.log`(`/home/vcs/vcmc/logs/vcmc.log`). `Settings.vcs_vcsm_log_path`/`vcs_vcmm_log_path`/`vcs_vcmc_log_path` 기본값으로 반영, `.env`로 override 가능.
- [x] VCS SSH 접속 정보/인증 방식은 확인됨(비밀번호 인증) — **호스트/계정은 보안상 이 문서·저장소에 기록하지 않고 각자 `.env`에만 채운다.** (2026-07-29 추가) `.env`는 여전히 기본값을 제공하지만, 그 위에 얹는 오버라이드를 **대시보드("설정" 메뉴)에서도 편집할 수 있게** 확장했다 — `VcsSettings`(DB 싱글턴 1행, `backend/app/models/vcs_settings.py`)가 오버라이드를 저장하고, `app/services/vcs_settings_store.py`의 `resolve_vcs_target()`/`resolve_sipp_target()`/`resolve_sipp_exec_mode()`가 "DB 오버라이드 > `.env`" 순으로 병합해서 실제 `SSHTarget`을 만든다. SSH 연결이 필요한 모든 지점(VoLTE/McPTT executor, VCS 샘플 파일 목록 조회, 헬스체크)이 이 resolver를 거치도록 정리했다 — `SSHTarget.from_vcs_settings()`/`from_sipp_settings()`를 직접 호출하는 코드는 이제 없어야 한다(DB 오버라이드를 놓치게 됨). API는 `GET/PATCH /api/settings/vcs` + `POST /api/settings/{vcs,sipp}/test-connection`(저장 전 실제 접속 테스트). 비밀번호는 응답에 절대 원문으로 안 내려가고 `*_password_set`(bool)만 알려주며, DB에는 평문 저장(.env와 동일한 신뢰 경계 — 별도 암호화는 TBD).
- [ ] Pass/Fail 판정 세부 기준(케이스별로 다를 수 있음 — 성공 기준 외 추가 검증 항목 여부)
- [x] **실 서버 장애: SSH 로그 tail이 예외/로그 하나 없이 조용히 멈추고 TestRun이 영원히 "running"에 머무는 문제** (2026-07-29 실 서버 backend.log로 근본 원인 확인, 총 두 지점) — `SSHConnector`(`backend/app/services/ssh_connector/client.py`)의 `asyncssh` 호출 중 응답을 무기한 기다릴 수 있는 지점 두 곳에 전부 타임아웃이 없었다:
  1. `connect()`가 `asyncssh.connect()`를 타임아웃 없이 호출 — asyncssh의 `login_timeout`(기본 120초)은 TCP 연결이 이미 수립된 뒤에야 시작되므로, TCP handshake 자체가 응답 없이 멈추는 경우(네트워크 순단 등)는 전혀 보호되지 않는다.
  2. (2026-07-29 추가 확인) `tail_file()`의 `finally: process.terminate(); await process.wait_closed()`와 `close()`의 `await self._conn.wait_closed()` — `terminate()`/`close()` 자체는 신호만 보내고 바로 리턴되지만, 그 뒤 원격이 채널/커넥션 종료를 확인(`Received channel close`)해줄 때까지 기다리는 `wait_closed()`에도 타임아웃이 없었다. 실 서버 로그에서 tail 채널 3개 모두 `Sending TERM signal`까지만 찍히고 그 뒤 `Received channel close`/`Channel closed`가 전혀 없이 멈추는 패턴으로 확인됐다 — 이쪽이 실제로 더 흔하게 걸리는 경로였다(매 Test Run 종료 시 `session.stop()`이 반드시 거치는 정상 종료 경로이기 때문).
  두 경우 모두 `SshTailSource`(재연결 또는 정상 종료)가 이 지점에서 멈추면, `VolteBasicCallExecutor.run()`의 `await session.stop()`(→ `asyncio.gather`로 해당 태스크를 기다림)도 영원히 끝나지 않아 최종 상태 반영(`persist_results`/`job_runner.set_status`)까지 도달하지 못했다 — `timeout_sec`(기본 30초)이 지나도 TestRun이 `running`에서 멈춰있던 증상과 정확히 일치. `Settings.vcs_ssh_connect_timeout_sec`(기본 15초)/`vcs_ssh_close_timeout_sec`(기본 10초)로 두 지점 모두 `asyncio.wait_for`로 감싸 강제 타임아웃을 걸도록 수정(`SSHConnector.__init__`/`connect`/`close`, `tail_file`). 타임아웃 시 명시적으로 로그를 남기므로(`connect()`는 재시도 대상 예외로 raise, `wait_closed()` 쪽은 이미 정리 중이라 경고만 남기고 진행), 무한 대기 대신 유한 시간 안에 실패·복구·에러 보고 중 하나로 귀결된다.
- [x] **실행기 예외가 대시보드에 안 보이던 문제(2026-07-30)** — `job_factory()`가 던진 예외를 `job_runner._run_wrapper`가 로그로만 남기고 `TestRun.result_summary`에는 기록하지 않아서, 사용자가 단순 설정 실수(예: `protocol_params.target_host` 누락)를 진단하려면 매번 서버에 SSH로 접속해 `backend.log`를 봐야 했다. `_run_wrapper`의 예외 핸들러가 `result_summary=json.dumps({"error": f"{type(exc).__name__}: {exc}"})`를 남기도록 수정(`backend/app/job_runner/runner.py`). 이 김에 프론트 타입 버그도 같이 발견해 고쳤다 — `TestRun.result_summary`는 백엔드가 JSON 문자열(`str | None`)로 내려주는데 프론트 타입이 `Record<string, unknown>`으로 잘못돼 있어 표시 시 이중 JSON 인코딩이 나던 문제(`frontend/src/api/types.ts`, `ExecutionPage.tsx`의 `formatResultSummary()`). Playwright로 "결과 요약" 섹션에 에러 메시지가 정상 렌더링되는 것까지 확인함.
- [x] **McPTT 시나리오 XML select box가 permission denied로 실패할 수 있던 문제(2026-07-30)** — `GET /api/vcs/mcptt-scenario-files`(`list_mcptt_scenario_files`, `app/services/mcptt/scenario_files.py`)가 `mcptt_sim_dir`(기본 `/root/mcptt_sim`) 목록을 일반 `run_command()`로 조회했는데, 이 경로가 `/root` 아래라 root 직접 SSH 로그인이 막힌 환경(`sipp_ssh_root_password` 설정된 배포)에서는 로그인 계정(sysadm)에 `/root` traverse 권한이 없어 `ls`가 permission denied로 실패할 수 있었다 — 실제 시뮬레이터 실행(`McpttBasicCallExecutor._run_sipp_remote`)은 이미 이 경우 `run_command_as_su()`로 root 권한으로 도는 것과 어긋나 있었다. `list_mcptt_scenario_files`도 `sipp_ssh_root_password`가 설정돼 있으면 동일하게 su root로 `ls`하도록 수정, 단위 테스트 추가(`test_list_mcptt_scenario_files_uses_su_root_when_password_configured`).
- [x] **McPTT `protocol_params` 수동 입력 부담 축소(2026-07-30 요청)** — `target_host`/`target_port`/`local_ip`/`local_port`/`control_port`를 매 Test Case마다 JSON에 직접 채워야 했다. `sipp_exec_mode="ssh"`일 때: `target_host`는 protocol_params에 명시(기존 `target_ip` 키 포함)가 없으면 대시보드 "설정"에 저장된 VCS 접속 IP(`resolve_vcs_target()`로 이미 구해둔 값)를 그대로 쓰고, 나머지 4개는 `Settings.mcptt_sim_target_port`(5060)/`mcptt_sim_local_ip`(192.168.7.65)/`mcptt_sim_local_port`(5080)/`mcptt_sim_control_port`(6061) 고정값으로 채운다(`McpttBasicCallExecutor.run`, `dict(params)` + `.setdefault()` — 명시적으로 넣은 값이 항상 우선). `target_host`만 VCS 설정을 실행 시점에 동적으로 읽어오고 나머지는 Settings 고정값인 이유는 VCS IP는 대시보드에서 바뀔 수 있지만 시뮬레이터 로컬 바인딩 정보는 배포 환경마다 고정이기 때문. (구현 중 `{**defaults, **params}` 방식은 `target_host`가 항상 우선해버려 레거시 `target_ip`-only 케이스를 깨는 버그가 있었다 — 기존 테스트로 잡아서 `setdefault` 방식으로 교체.)

Log Parser & Call Flow Agent는 위에서 이미 확보된 로그 샘플을 기준으로 `VctpLogAdapter`/`VcsmLogAdapter`/`VcmmLogAdapter`/`VcmcLogAdapter` 구현을 우선 진행할 수 있다. 실패 케이스 로그가 추가되면 이 문서의 §3, §6, §9를 다시 갱신한다. VCS 실 서버 연동 상세(pcap 샘플 select box, vctp 정지/시작 명령, 로그 경로, SIPp 원격 실행)는 §3, `docs/DEPLOYMENT.md`에도 반영되어 있다.
