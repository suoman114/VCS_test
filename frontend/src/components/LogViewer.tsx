/**
 * 실시간 로그 뷰어.
 *
 * - "실시간" 영역: WebSocket으로 들어온 최근 MAX_LINES_PER_CHANNEL(500)줄만
 *   보여준다(store/logStore.ts). 그 이상 쌓인 과거 로그는 브라우저 메모리에
 *   유지하지 않는다.
 * - "과거 로그 불러오기": `GET /api/test-runs/{id}/events` 페이지네이션으로
 *   필요할 때만 추가 조회한다(가상 스크롤 대신 단순 offset 기반 "더 보기").
 * - VCS 로그 / SIPp 로그 탭으로 구분 표시, 자동 스크롤 옵션 지원.
 */
import { useEffect, useRef, useState } from "react";
import { useLogStore } from "../store/logStore";
import { testRunsApi } from "../api/testRuns";
import type { CallEvent, LogChannel } from "../api/types";
import "./LogViewer.css";

const TABS: { key: LogChannel; label: string }[] = [
  { key: "vcs_log", label: "VCS 로그" },
  { key: "sipp_log", label: "SIPp 로그" },
];

const HISTORY_PAGE_SIZE = 100;

export function LogViewer({ runId }: { runId: string | null }) {
  const [activeTab, setActiveTab] = useState<LogChannel>("vcs_log");
  const [autoScroll, setAutoScroll] = useState(true);
  const [history, setHistory] = useState<CallEvent[]>([]);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyTotal, setHistoryTotal] = useState<number | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const liveLines = useLogStore((state) => (runId ? state.channels[activeTab] : []));
  const channelError = useLogStore((state) => (runId ? state.channelErrors[activeTab] : null));

  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    // 탭/실행이 바뀌면 과거 로그 섹션을 초기화한다.
    setHistory([]);
    setHistoryOffset(0);
    setHistoryTotal(null);
    setHistoryError(null);
  }, [runId, activeTab]);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [liveLines, autoScroll]);

  async function loadMoreHistory() {
    if (!runId) return;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const res = await testRunsApi.getEvents(runId, { limit: HISTORY_PAGE_SIZE, offset: historyOffset });
      const filtered = res.items.filter((ev) => channelOf(ev.source) === activeTab);
      setHistory((prev) => [...prev, ...filtered]);
      setHistoryOffset((prev) => prev + res.items.length);
      setHistoryTotal(res.total);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : "과거 로그 조회 실패");
    } finally {
      setHistoryLoading(false);
    }
  }

  return (
    <div className="log-viewer">
      <div className="log-viewer-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            className={tab.key === activeTab ? "log-tab log-tab-active" : "log-tab"}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
        <label className="log-autoscroll">
          <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} />
          자동 스크롤
        </label>
      </div>

      {channelError && <div className="log-channel-error">채널 오류: {channelError}</div>}

      <div className="log-viewer-body" ref={scrollRef}>
        {!runId && <div className="log-empty">실행 중인 Test Run이 없습니다.</div>}
        {runId && liveLines.length === 0 && <div className="log-empty">아직 수신된 로그가 없습니다.</div>}
        {liveLines.map((l) => (
          <div key={l.seq} className="log-line">
            <span className="log-seq">#{l.seq}</span>
            <span className="log-source">[{l.source}]</span>
            <span className="log-text">{l.line}</span>
          </div>
        ))}
      </div>

      <div className="log-history">
        <div className="log-history-header">
          <span>과거 로그(파싱된 CallEvent, 페이지네이션)</span>
          <button onClick={loadMoreHistory} disabled={!runId || historyLoading}>
            {historyLoading ? "불러오는 중..." : "더 보기"}
          </button>
        </div>
        {historyError && <div className="log-channel-error">{historyError}</div>}
        {historyTotal !== null && (
          <div className="log-history-count">
            {history.length} / {historyTotal}건 로드됨
          </div>
        )}
        <div className="log-history-body">
          {history.map((ev) => (
            <div key={ev.id} className="log-line">
              <span className="log-seq">#{ev.seq_no}</span>
              <span className="log-source">[{ev.source}]</span>
              <span className="log-text">{ev.raw_line}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function channelOf(source: CallEvent["source"]): LogChannel {
  return source === "sipp_log" ? "sipp_log" : "vcs_log";
}
