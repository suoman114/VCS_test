/**
 * VCS 서버 자체를 조회하는 보조 API 클라이언트 (CONFIRMED — backend/app/api/vcs.py).
 *
 *   GET /api/vcs/volte-sample-files
 *
 * VCS에 실제 SSH 연결이 안 되면 502로 응답한다 — 폼에서는 이 경우를 별도로
 * 안내(연결 실패, 파일명 직접 입력으로 폴백)한다.
 */
import { apiClient } from "./client";

export interface VolteSampleFilesResponse {
  items: string[];
}

export const vcsApi = {
  volteSampleFiles: (): Promise<VolteSampleFilesResponse> =>
    apiClient.get<VolteSampleFilesResponse>("/vcs/volte-sample-files"),
};
