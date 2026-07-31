/**
 * 헬스체크 클라이언트 (CONFIRMED 엔드포인트 존재 / ASSUMED 세부 필드).
 *
 *   GET /api/health → {"status": "ok"} (현재 백엔드 구현, backend/app/api/health.py)
 *
 * VCS SSH 연결, SIPp 실행 가능 여부 등 세부 헬스체크 필드는 아직 백엔드에
 * 없다. 확장되면 HealthResponse 타입과 이 함수만 갱신하면 된다.
 */
import { apiClient } from "./client";
import type { HealthResponse } from "./types";

export const healthApi = {
  check: (): Promise<HealthResponse> => apiClient.get<HealthResponse>("/health"),
};
