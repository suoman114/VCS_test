/**
 * 실시간 로그 뷰어.
 *
 * - "실시간" 영역: WebSocket으로 들어온 최근 MAX_LINES_PER_SOURCE(500)줄만
 *   보여준다(store/logStore.ts). 그 이상 쌓인 과거 로그는 브라우저 메모리에
 *   유지하지 않는다.
 * - "과거 로그 불러오기": `GET /api/test-runs/{id}/events` 페이지네이션으로
 *   필요할 때만 추가 조회한다(가상 스크롤 대신 단순 offset 기반 "더 보기").
 * - 프로세스별(vcsm/vcmm/vctp/vcmc/sipp) 탭으로 구분 표시, 자동 스크롤 옵션 지원.
 *   탭은 고정 목록이 아니라 실제로 로그가 들어온 source를 기준으로 동적으로
 *   생긴다 — VoLTE 실행은 vcsm/vcmm/vctp만, McPTT 실행은 vcmc/vcmm(+sipp)만
 *   나타난다.
 */
import { useEffect, useRef, useState } from "react";
import { useLogStore } from "../store/logStore";
import { testRunsApi } from "../api/testRuns";
import type { CallEvent } from "../api/types";
import "./LogViewer.css";

/** 알려진 소스는 한글 라벨 + 표시 순서를 붙인다. 그 외(향후 추가되는 소스 등)는 이름 그대로, 맨 뒤에. */
const KNOWN_SOURCE_LABELS: Record<string, string> = {
  vcsm_log: "VCSM (SIP)",
  vcmc_log: "VCMC (SIP+MCPTT)",
  vcmm_log: "VCMM (녹취 제어)",
  vctp_log: "vctp (패킷 릴레이)",
  sipp_log: "SIPp",
};
const SOURCE_ORDER = ["vcsm_log", "vcmc_log", "vcmm_log", "vctp_log", "sipp_log"];

function sortSources(sources: string[]): string[] {
  return [...sources].sort((a, b) => {
    const ia = SOURCE_ORDER.indexOf(a);
    const ib = SOURCE_ORDER.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });
}

function labelOf(source: string): string {
  return KNOWN_SOURCE_LABELS[source] ?? source;
}

const HISTORY_PAGE_SIZE = 100;

export function LogViewer({ runId }: { runId: string | null }) {
  const bySource = useLogStore((state) => state.bySource);
  const sourceErrors = useLogStore((state) => state.sourceErrors);

  const sources = sortSources(Object.keys(bySource));
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [history, setHistory] = useState<CallEvent[]>([]);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyTotal, setHistoryTotal] = useState<number | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  // 아직 선택된 탭이 없거나(첫 로그 도착 전), 선택된 탭의 소스가 더 이상 없으면
  // (run 전환 등) 사용 가능한 첫 소스로 자동 전환한다.
  useEffect(() => {
    if (sources.length === 0) {
      if (activeTab !== null) setActiveTab(null);
      return;
    }
    if (activeTab === null || !sources.includes(activeTab)) {
      setActiveTab(sources[0]);
    }
    // sources 배열은 매 렌더마다 새로 만들어지므로 join한 값으로 비교한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources.join(","), activeTab]);

  const liveLines = activeTab ? bySource[activeTab] ?? [] : [];
  const channelError = activeTab ? sourceErrors[activeTab] ?? null : null;

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
    if (!runId || !activeTab) return;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const res = await testRunsApi.getEvents(runId, { limit: HISTORY_PAGE_SIZE, offset: historyOffset });
      const filtered = res.items.filter((ev) => ev.source === activeTab);
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
        {sources.length === 0 && <span className="log-tabs-empty">로그 소스 대기 중...</span>}
        {sources.map((source) => (
          <button
            key={source}
            className={source === activeTab ? "log-tab log-tab-active" : "log-tab"}
            onClick={() => setActiveTab(source)}
          >
            {labelOf(source)}
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
          <button onClick={loadMoreHistory} disabled={!runId || !activeTab || historyLoading}>
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
