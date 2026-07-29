/**
 * 실시간 로그 뷰어 상태 (Zustand).
 *
 * 프로세스(vcsm_log/vcmm_log/vctp_log/vcmc_log/sipp_log 등)별로 최근
 * MAX_LINES_PER_SOURCE 줄만 메모리에 유지한다 (CLAUDE.md 원칙: 대량 로그를
 * 브라우저가 전부 들고 있지 않는다. 필요하면 `api/testRuns.ts`의 getEvents()로
 * 과거 구간을 페이지네이션 조회한다).
 *
 * 예전엔 채널(vcs_log/sipp_log) 2개로만 묶어서 vcsm/vcmm 로그가 한 탭에
 * 섞여 나왔다 — 프로세스별 탭 요구사항에 맞춰 WS 메시지의 `source`(세부
 * 프로세스명, 예: "vcsm_log")를 키로 쓰도록 바꿨다. 어떤 소스가 실제로
 * 존재하는지는 실행 프로토콜(VoLTE/McPTT)마다 다르므로 고정 키 목록 대신
 * 런타임에 들어오는 대로 동적으로 채운다.
 *
 * `jumpTarget`: Call Flow에서 메시지를 클릭했을 때 로그 뷰어가 어느
 * source/seq_no로 이동해야 하는지 담는 1회성 신호다. LogViewer가 소비하고
 * 나면 `clearJumpTarget()`으로 지운다(같은 지점을 다시 클릭해도 반응하도록).
 */
import { create } from "zustand";
import type { TestRunStatus } from "../api/types";

export const MAX_LINES_PER_SOURCE = 500;

export interface LogLine {
  seq: number;
  source: string;
  line: string;
  ts: string;
}

export interface JumpTarget {
  source: string;
  seqNo: number;
}

interface LogState {
  /** 현재 구독 중인 test run id (null이면 미구독). */
  activeRunId: string | null;
  /** WebSocket으로 수신한 run 상태 (REST 폴링 값과 별개로 실시간 갱신용). */
  liveStatus: TestRunStatus | null;
  /** 프로세스별(vcsm_log 등) 최근 로그 라인. 처음 보는 source는 접근 시 빈 배열로 취급한다. */
  bySource: Record<string, LogLine[]>;
  sourceErrors: Record<string, string | null>;
  jumpTarget: JumpTarget | null;

  setActiveRunId: (runId: string | null) => void;
  appendLine: (source: string, line: LogLine) => void;
  setSourceError: (source: string, message: string | null) => void;
  setLiveStatus: (status: TestRunStatus) => void;
  setJumpTarget: (target: JumpTarget) => void;
  clearJumpTarget: () => void;
  reset: () => void;
}

export const useLogStore = create<LogState>((set) => ({
  activeRunId: null,
  liveStatus: null,
  bySource: {},
  sourceErrors: {},
  jumpTarget: null,

  setActiveRunId: (runId) =>
    set({ activeRunId: runId, bySource: {}, sourceErrors: {}, liveStatus: null, jumpTarget: null }),

  appendLine: (source, line) =>
    set((state) => {
      const existing = state.bySource[source] ?? [];
      const next = [...existing, line];
      const trimmed = next.length > MAX_LINES_PER_SOURCE ? next.slice(next.length - MAX_LINES_PER_SOURCE) : next;
      return { bySource: { ...state.bySource, [source]: trimmed } };
    }),

  setSourceError: (source, message) =>
    set((state) => ({ sourceErrors: { ...state.sourceErrors, [source]: message } })),

  setLiveStatus: (status) => set({ liveStatus: status }),

  setJumpTarget: (target) => set({ jumpTarget: target }),
  clearJumpTarget: () => set({ jumpTarget: null }),

  reset: () => set({ activeRunId: null, liveStatus: null, bySource: {}, sourceErrors: {}, jumpTarget: null }),
}));
