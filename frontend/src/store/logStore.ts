/**
 * 실시간 로그 뷰어 상태 (Zustand).
 *
 * 채널(vcs_log/sipp_log)별로 최근 MAX_LINES_PER_CHANNEL 줄만 메모리에 유지한다
 * (CLAUDE.md 원칙: 대량 로그를 브라우저가 전부 들고 있지 않는다. 필요하면
 * `api/testRuns.ts`의 getEvents()로 과거 구간을 페이지네이션 조회한다).
 */
import { create } from "zustand";
import type { LogChannel, TestRunStatus } from "../api/types";

export const MAX_LINES_PER_CHANNEL = 500;

export interface LogLine {
  seq: number;
  source: string;
  line: string;
  ts: string;
}

interface LogState {
  /** 현재 구독 중인 test run id (null이면 미구독). */
  activeRunId: string | null;
  /** WebSocket으로 수신한 run 상태 (REST 폴링 값과 별개로 실시간 갱신용). */
  liveStatus: TestRunStatus | null;
  channels: Record<LogChannel, LogLine[]>;
  channelErrors: Record<LogChannel, string | null>;

  setActiveRunId: (runId: string | null) => void;
  appendLine: (channel: LogChannel, line: LogLine) => void;
  setChannelError: (channel: LogChannel, message: string | null) => void;
  setLiveStatus: (status: TestRunStatus) => void;
  reset: () => void;
}

const emptyChannels = (): Record<LogChannel, LogLine[]> => ({
  vcs_log: [],
  sipp_log: [],
});

const emptyErrors = (): Record<LogChannel, string | null> => ({
  vcs_log: null,
  sipp_log: null,
});

export const useLogStore = create<LogState>((set) => ({
  activeRunId: null,
  liveStatus: null,
  channels: emptyChannels(),
  channelErrors: emptyErrors(),

  setActiveRunId: (runId) =>
    set({ activeRunId: runId, channels: emptyChannels(), channelErrors: emptyErrors(), liveStatus: null }),

  appendLine: (channel, line) =>
    set((state) => {
      const next = [...state.channels[channel], line];
      const trimmed = next.length > MAX_LINES_PER_CHANNEL ? next.slice(next.length - MAX_LINES_PER_CHANNEL) : next;
      return { channels: { ...state.channels, [channel]: trimmed } };
    }),

  setChannelError: (channel, message) =>
    set((state) => ({ channelErrors: { ...state.channelErrors, [channel]: message } })),

  setLiveStatus: (status) => set({ liveStatus: status }),

  reset: () => set({ activeRunId: null, liveStatus: null, channels: emptyChannels(), channelErrors: emptyErrors() }),
}));
