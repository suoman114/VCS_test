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
  status: TestRunStatus;
  started_at: string | null;
  ended_at: string | null;
  target_host: string | null;
  raw_log_path: string | null;
  result_summary: Record<string, unknown> | null;
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

export interface CallFlowResponse {
  run_id: string;
  mermaid_source: string;
  generated_at: string;
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
}

export type WsMessage = WsLogMessage | WsLogSourceErrorMessage | WsStatusMessage | WsCallFlowMessage;

// ---------------------------------------------------------------------------
// Health check (CONFIRMED — backend/app/api/health.py: {"status": "ok"} 만 반환)
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string;
  // TODO(ASSUMED): VCS SSH 연결/SIPp 실행가능 여부 등 세부 헬스체크 필드는
  // 아직 백엔드에 없다. 확장되면 아래 optional 필드로 매핑한다.
  vcs_ssh?: "ok" | "error" | "unknown";
  sipp?: "ok" | "error" | "unknown";
}
