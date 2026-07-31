/**
 * 백엔드 API 타입 정의.
 *
 * TestCase 관련 타입은 testcase-manager-agent가 확정한 스펙
 * (`backend/app/schemas/test_case.py`)을 그대로 반영한 것이다 (CONFIRMED).
 *
 * TestRun / CallEvent / CallFlow / WebSocket 메시지 타입은 아직 backend-agent가
 * 구현 중인 "가정된 스펙"이다 (ASSUMED). 실제 스펙이 확정되면 이 파일과
 * `api/testRuns.ts`, `api/useTestRunSocket.ts`만 수정하면 되도록 다른 코드는
 * 이 타입들을 통해서만 백엔드와 통신한다.
 */

// ---------------------------------------------------------------------------
// TestCase (CONFIRMED — backend/app/schemas/test_case.py 기준)
// ---------------------------------------------------------------------------

export type TestCaseCategory = "volte" | "mcptt";
export type TestCaseType = "basic_call" | "performance" | "abnormal";

export interface TestCaseBase {
  name: string;
  description?: string | null;
  category: TestCaseCategory;
  test_type: TestCaseType;
  config_ref: string;
  protocol_params: Record<string, unknown>;
  pass_criteria: Record<string, unknown>;
  yaml_path?: string | null;
}

export interface TestCaseCreate extends TestCaseBase {
  id?: string | null;
}

export interface TestCaseUpdate {
  name?: string;
  description?: string | null;
  category?: TestCaseCategory;
  test_type?: TestCaseType;
  config_ref?: string;
  protocol_params?: Record<string, unknown>;
  pass_criteria?: Record<string, unknown>;
  yaml_path?: string | null;
}

export interface TestCaseRead extends TestCaseBase {
  id: string;
  created_at: string;
  updated_at: string;
}

export interface TestCaseListResponse {
  items: TestCaseRead[];
  total: number;
}

export interface TestCaseListParams {
  category?: TestCaseCategory;
  test_type?: TestCaseType;
  name?: string;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------------------
// TestRun (ASSUMED — backend-agent가 병렬로 구현 중. 최종 스펙 확정 시
// 이 섹션과 api/testRuns.ts, api/useTestRunSocket.ts만 갱신하면 된다.)
// ---------------------------------------------------------------------------

export type TestRunStatus =
  | "pending"
  | "running"
  | "parsing"
  | "done"
  | "failed"
  | "error";

export interface TestRun {
  id: string;
  test_case_id: string;
  // TestCase와 조인해서 채워주는 파생 필드(2026-07-30 UI 개선 요청) — 대시보드/
  // 이력/실행 화면에 UUID 대신 사람이 읽을 수 있는 이름을 보여주기 위함.
  // TestCase가 없어졌거나 조인에 실패하면 null(이 경우 test_case_id로 폴백해야 함).
  test_case_name: string | null;
  status: TestRunStatus;
  started_at: string | null;
  ended_at: string | null;
  target_host: string | null;
  raw_log_path: string | null;
  // 백엔드는 JSON을 담은 "문자열"로 내려준다(app/schemas/test_run.py:
  // result_summary: str | None, DB에도 Text 컬럼에 json.dumps() 결과를 그대로
  // 저장) — 파싱된 객체가 아니다. 예전엔 이 타입이 Record<string, unknown>으로
  // 잘못 선언돼 있어서, 화면에서 JSON.stringify(문자열)을 한 번 더 해버려
  // 이스케이프된 문자열이 그대로 보이는 버그가 있었다(2026-07-30 확인).
  result_summary: string | null;
}

export interface TestRunListResponse {
  items: TestRun[];
  total: number;
}

export interface TestRunListParams {
  test_case_id?: string;
  status?: TestRunStatus;
  limit?: number;
  offset?: number;
}

/**
 * 대시보드 통계 카드용 집계 (CONFIRMED — `app.schemas.test_run.TestRunStatsBucket`).
 * `pass_rate`는 종료된 실행(done/failed/error) 기준이라 대기/실행 중인 run은
 * 분모에서 빠진다 — 종료된 실행이 하나도 없으면 `null`("-"로 표시).
 */
export interface TestRunStatsBucket {
  total: number;
  passed: number;
  failed: number;
  error: number;
  in_progress: number;
  pass_rate: number | null;
}

export interface TestRunStatsResponse {
  overall: TestRunStatsBucket;
  by_category: Partial<Record<TestCaseCategory, TestRunStatsBucket>>;
  recent: TestRunStatsBucket;
  recent_days: number;
}

/**
 * Call Flow의 메시지(화살표) 하나 -> 원본 CallEvent 참조 (CONFIRMED —
 * `app.schemas.test_run.CallFlowMessageRead`). `index`는 렌더된 Mermaid
 * `.messageText` 엘리먼트 순서와 1:1 대응해서, 클릭 시 어떤 CallEvent(로그
 * 라인)로 이동해야 하는지 알려준다.
 */
export interface CallFlowMessage {
  index: number;
  seq_no: number;
  source: CallEventSource;
  call_id: string | null;
}

export interface CallFlowResponse {
  run_id: string;
  mermaid_source: string;
  generated_at: string;
  messages: CallFlowMessage[];
}

/** 콜별 Call Flow 선택 드롭다운용 call_id 목록 (CONFIRMED —
 * `app.schemas.test_run.CallIdListResponse`). 처음 등장한 순서를 유지한다. */
export interface CallIdListResponse {
  items: string[];
}

/**
 * 리포트용 파생 통계 (CONFIRMED — `app.schemas.test_run.ReportStatsResponse`,
 * `GET /test-runs/{id}/report-stats`, 2026-07-30 추가). 콜 설정 시간은
 * SIP INVITE~200 OK가 아니라 recording_start_req~res(녹취 개시) 기준이다.
 */
export interface HistogramBin {
  range_start_ms: number;
  range_end_ms: number;
  count: number;
}

export interface SetupTimeStats {
  count: number;
  min_ms: number;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
  max_ms: number;
  histogram: HistogramBin[];
}

export interface ConcurrencyPoint {
  offset_sec: number;
  concurrent_calls: number;
}

export interface ReportStatsResponse {
  setup_time: SetupTimeStats | null;
  concurrency_series: ConcurrencyPoint[];
  bucket_seconds: number;
}

export type CallEventSource =
  | "vctp_log"
  | "vcsm_log"
  | "vcmm_log"
  | "vcmc_log"
  | "sipp_log";

export interface CallEvent {
  id: string | number;
  run_id: string;
  ts: string;
  source: CallEventSource;
  raw_line: string;
  parsed_type: string | null;
  call_id: string | null;
  reason_code: string | null;
  seq_no: number;
}

export interface CallEventListResponse {
  items: CallEvent[];
  total: number;
}

export interface CallEventListParams {
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------------------
// WebSocket 실시간 로그 메시지 (log-collector-agent 확정분 — CONFIRMED)
// ---------------------------------------------------------------------------

/** VCS 로그(vctp/vcsm/vcmm/vcmc) 또는 SIPp 로그 채널 구분. */
export type LogChannel = "vcs_log" | "sipp_log";

export interface WsLogMessage {
  type: "log";
  run_id: string;
  channel: LogChannel;
  source: string;
  seq: number;
  line: string;
  ts: string;
}

export interface WsLogSourceErrorMessage {
  type: "log_source_error";
  run_id: string;
  channel: string;
  source: string;
  message: string;
  ts: string;
}

/**
 * 실행 상태 변경 브로드캐스트. 정확한 필드명은 backend-agent가 아직 확정하지
 * 않았다 (ASSUMED) — status 값은 TestRunStatus 를 따른다고 가정한다.
 */
export interface WsStatusMessage {
  type: "status";
  run_id: string;
  status: TestRunStatus;
  ts: string;
}

/**
 * Call Flow(Mermaid) 갱신 브로드캐스트 (CONFIRMED —
 * `execution_common.persist_call_flow`/`persist_results`). 실행 도중 폴링마다,
 * 그리고 종료 시점에 한 번 더 push된다 — 대시보드가 폴링 없이도 실시간으로
 * Call Flow를 갱신할 수 있게 한다.
 */
export interface WsCallFlowMessage {
  type: "call_flow";
  run_id: string;
  mermaid_source: string;
  generated_at: string;
  messages: CallFlowMessage[];
}

export type WsMessage = WsLogMessage | WsLogSourceErrorMessage | WsStatusMessage | WsCallFlowMessage;

// ---------------------------------------------------------------------------
// Health check (CONFIRMED — backend/app/api/health.py)
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string;
  // VCS SSH 연결/SIPp 실행 가능 여부를 실제로 접속 시도해서 확인한 결과.
  // "unknown"은 호스트가 아직 설정되지 않은 상태(.env/대시보드 설정 둘 다 없음).
  vcs_ssh?: "ok" | "error" | "unknown";
  sipp?: "ok" | "error" | "unknown";
}

// ---------------------------------------------------------------------------
// VCS/SIPp 접속 설정 (CONFIRMED — backend/app/api/settings.py, app/schemas/vcs_settings.py)
//
// GET은 "효과값"(effective value)을 돌려준다 — 대시보드에서 오버라이드한 값이
// 있으면 그 값, 없으면 .env(Settings) 기본값이 그대로 보인다. 비밀번호는
// 원문으로 절대 내려오지 않고 `*_password_set`(설정 여부)만 알려준다.
// ---------------------------------------------------------------------------

export type SippExecMode = "local" | "ssh";

export interface VcsSettings {
  vcs_ssh_host: string | null;
  vcs_ssh_port: number;
  vcs_ssh_username: string | null;
  vcs_ssh_password_set: boolean;
  vcs_ssh_private_key_path: string | null;
  vcs_ssh_known_hosts: string | null;

  sipp_exec_mode: SippExecMode;
  sipp_ssh_host: string | null;
  sipp_ssh_port: number;
  sipp_ssh_username: string | null;
  sipp_ssh_password_set: boolean;
  sipp_ssh_private_key_path: string | null;
  // root 직접 SSH 로그인이 막힌 환경(2026-07-29)에서 sipp_ssh_username 접속 후
  // `su - root`로 전환할 때 쓰는 비밀번호. 설정돼 있으면 SIPp 실행 관련 원격
  // 명령을 root 권한으로 돌린다.
  sipp_ssh_root_password_set: boolean;

  // VCS 녹취 DB(MariaDB) 접속 정보 — VoLTE 중복 Call-ID 자동 정리용(2026-07-30).
  // 셋 다 채워져 있어야 기능이 켜진다(app/services/volte/recording_cleanup.py).
  vcs_mariadb_user: string | null;
  vcs_mariadb_password_set: boolean;
  vcs_mariadb_database: string | null;

  updated_at: string | null;
}

/** PATCH 요청 바디. 보낸 필드만 갱신된다 — 빈 문자열("")은 오버라이드 해제(.env로
 * 복귀), 비밀번호 필드를 아예 안 보내면 기존 값이 유지된다(마스킹 표시 유지용). */
export interface VcsSettingsUpdate {
  vcs_ssh_host?: string;
  vcs_ssh_port?: number;
  vcs_ssh_username?: string;
  vcs_ssh_password?: string;
  vcs_ssh_private_key_path?: string;
  vcs_ssh_known_hosts?: string;

  sipp_exec_mode?: SippExecMode;
  sipp_ssh_host?: string;
  sipp_ssh_port?: number;
  sipp_ssh_username?: string;
  sipp_ssh_password?: string;
  sipp_ssh_private_key_path?: string;
  sipp_ssh_root_password?: string;

  vcs_mariadb_user?: string;
  vcs_mariadb_password?: string;
  vcs_mariadb_database?: string;
}

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
}
