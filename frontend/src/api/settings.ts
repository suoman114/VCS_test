/**
 * VCS/SIPp 접속 설정 REST 클라이언트 (CONFIRMED — backend/app/api/settings.py).
 *
 *   GET   /api/settings/vcs
 *   PATCH /api/settings/vcs
 *   POST  /api/settings/vcs/test-connection
 *   POST  /api/settings/sipp/test-connection
 */
import { apiClient } from "./client";
import type { ConnectionTestResult, VcsSettings, VcsSettingsUpdate } from "./types";

export const settingsApi = {
  getVcs: (): Promise<VcsSettings> => apiClient.get<VcsSettings>("/settings/vcs"),

  updateVcs: (body: VcsSettingsUpdate): Promise<VcsSettings> =>
    apiClient.patch<VcsSettings>("/settings/vcs", body),

  testVcsConnection: (): Promise<ConnectionTestResult> =>
    apiClient.post<ConnectionTestResult>("/settings/vcs/test-connection"),

  testSippConnection: (): Promise<ConnectionTestResult> =>
    apiClient.post<ConnectionTestResult>("/settings/sipp/test-connection"),
};
