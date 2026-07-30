/**
 * TestRun REST 클라이언트 (ASSUMED — backend-agent가 병렬로 구현 중인 스펙).
 *
 * 아래 엔드포인트/스키마는 이번 작업 지시서에 명시된 "가정된 스펙"을 그대로
 * 반영한 것이며, 실제 backend 구현이 확정되면 이 파일만 고치면 되도록
 * 페이지/컴포넌트는 이 모듈을 통해서만 TestRun 데이터를 가져온다.
 *
 *   POST /api/test-cases/{id}/run              → TestRun 생성 후 반환
 *   GET  /api/test-runs/{id}                    → TestRun 단건 조회
 *   GET  /api/test-runs?test_case_id=&status=   → TestRun 목록(페이지네이션)
 *   GET  /api/test-runs/{id}/call-flow          → Mermaid 소스
 *   GET  /api/test-runs/{id}/events?limit=&offset= → 파싱된 CallEvent 목록
 */
import { apiClient } from "./client";
import type {
  CallEventListParams,
  CallEventListResponse,
  CallFlowResponse,
  CallIdListResponse,
  TestRun,
  TestRunListParams,
  TestRunListResponse,
  TestRunStatsResponse,
} from "./types";

export const testRunsApi = {
  /** 시험 실행 트리거. TODO(ASSUMED): 요청 바디가 필요할 수도 있음(현재는 없다고 가정). */
  trigger: (testCaseId: string): Promise<TestRun> =>
    apiClient.post<TestRun>(`/test-cases/${testCaseId}/run`),

  get: (runId: string): Promise<TestRun> => apiClient.get<TestRun>(`/test-runs/${runId}`),

  list: (params: TestRunListParams = {}): Promise<TestRunListResponse> =>
    apiClient.get<TestRunListResponse>("/test-runs", {
      test_case_id: params.test_case_id,
      status: params.status,
      limit: params.limit,
      offset: params.offset,
    }),

  /** `callId`를 주면 그 콜의 이벤트만으로 다시 생성한 Call Flow를 받는다
   * (McPTT 성능 시험처럼 한 Test Run에 콜이 여러 건 섞여 있을 때 콜 단위로
   * 구별해서 보기 위함, 2026-07-30 추가). */
  getCallFlow: (runId: string, callId?: string): Promise<CallFlowResponse> =>
    apiClient.get<CallFlowResponse>(`/test-runs/${runId}/call-flow`, callId ? { call_id: callId } : undefined),

  /** 콜별 Call Flow 선택 드롭다운용 call_id 목록. */
  getCallIds: (runId: string): Promise<CallIdListResponse> =>
    apiClient.get<CallIdListResponse>(`/test-runs/${runId}/call-ids`),

  getEvents: (runId: string, params: CallEventListParams = {}): Promise<CallEventListResponse> =>
    apiClient.get<CallEventListResponse>(`/test-runs/${runId}/events`, {
      limit: params.limit,
      offset: params.offset,
    }),

  /** 대시보드 통계 카드용 집계 (`GET /api/test-runs/stats`). */
  getStats: (): Promise<TestRunStatsResponse> => apiClient.get<TestRunStatsResponse>("/test-runs/stats"),

  /** 실행 중인 Test Run 종료(McPTT 성능 시험처럼 무기한 실행되는 시험의
   * 유일한 정상 종료 경로, `POST /api/test-runs/{id}/cancel`). 응답의
   * status는 아직 갱신 전일 수 있다(202) — 호출부가 계속 폴링해서 최종
   * 상태(보통 done)를 확인해야 한다. */
  cancel: (runId: string): Promise<TestRun> => apiClient.post<TestRun>(`/test-runs/${runId}/cancel`),
};
