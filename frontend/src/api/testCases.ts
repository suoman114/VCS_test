/**
 * TestCase REST 클라이언트 (CONFIRMED — testcase-manager-agent 완료분).
 *
 *   GET    /api/test-cases
 *   GET    /api/test-cases/{id}
 *   POST   /api/test-cases
 *   PATCH  /api/test-cases/{id}
 *   DELETE /api/test-cases/{id}
 */
import { apiClient } from "./client";
import type {
  TestCaseCreate,
  TestCaseListParams,
  TestCaseListResponse,
  TestCaseRead,
  TestCaseUpdate,
} from "./types";

export const testCasesApi = {
  list: (params: TestCaseListParams = {}): Promise<TestCaseListResponse> =>
    apiClient.get<TestCaseListResponse>("/test-cases", {
      category: params.category,
      test_type: params.test_type,
      name: params.name,
      limit: params.limit,
      offset: params.offset,
    }),

  get: (id: string): Promise<TestCaseRead> => apiClient.get<TestCaseRead>(`/test-cases/${id}`),

  create: (body: TestCaseCreate): Promise<TestCaseRead> =>
    apiClient.post<TestCaseRead>("/test-cases", body),

  update: (id: string, body: TestCaseUpdate): Promise<TestCaseRead> =>
    apiClient.patch<TestCaseRead>(`/test-cases/${id}`, body),

  remove: (id: string): Promise<void> => apiClient.delete<void>(`/test-cases/${id}`),
};
