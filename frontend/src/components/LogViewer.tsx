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
 *   나타난다. "실제로 로그가 들어온"의 기준은 두 가지를 합친 것이다: (a)
 *   WebSocket으로 들어온 라이브 소스(`bySource`), (b) 이미 DB에 저장된
 *   CallEvent의 source(`historicalSources`, 마운트 시 한 번 조회). (b)가
 *   없으면 시험 이력에서 이미 종료된 run의 로그를 볼 때(WS로 더 들어올
 *   라이브 데이터가 없음) 탭 자체가 하나도 안 생겨서 "과거 로그" 섹션조차
 *   못 여는 문제가 있었다.
 * - "클릭-투-로그": Call Flow에서 메시지를 클릭하면 `logStore.jumpTarget`이
 *   설정된다. 해당 source 탭으로 전환하고 "과거 로그"(파싱된 CallEvent)에서
 *   seq_no를 찾아 하이라이트한다. **반드시 과거 로그 쪽에서만 찾는다** —
 *   위쪽 "실시간" 라이브 라인의 `seq`는 원본(raw) 줄 단위로 1부터 증가하는
 *   완전히 다른 번호 체계라(`log_collector/session.py`의 `_consume()` 참고,
 *   파싱 전 raw tail 스트림 카운터) `CallFlowMessage.seq_no`(파싱된 CallEvent
 *   전역 순번, `assign_sequence()`)와는 무관하다.
 *
 *   스크롤은 `document.getElementById` 폴링 대신 **콜백 ref**로 처리한다 —
 *   하이라이트 대상 행이 마운트/갱신되는 바로 그 시점에 React가 호출해주므로
 *   "DOM에 반영됐는지" 타이밍을 직접 재보지 않아도 된다. 이전 버전은 별도
 *   `pendingJumpSeq` 상태 + `useEffect` 폴링으로 처리했는데, 못 찾은 상태가
 *   영영 안 풀리는 경로가 있었고(그 상태에 걸리면 자동 스크롤까지 함께
 *   멈춰버렸다), 그 상태를 지금 방식(파생 상태만 사용, 별도 "pending" 없음)
 *   으로 없앴다.
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
// 클릭-투-로그로 과거 로그를 찾을 때 쓰는 한 번의 대량 조회 크기. CLAUDE.md
// 기준 Test Run당 이벤트 수는 수십~수백 건 규모라 1000이면 충분히 큰
// 여유분이다(백엔드 /events의 limit 상한과 동일).
const JUMP_FETCH_LIMIT = 1000;
const HIGHLIGHT_DURATION_MS = 2500;

export function LogViewer({ runId }: { runId: string | null }) {
  const bySource = useLogStore((state) => state.bySource);
  const sourceErrors = useLogStore((state) => state.sourceErrors);
  const jumpTarget = useLogStore((state) => state.jumpTarget);
  const clearJumpTarget = useLogStore((state) => state.clearJumpTarget);

  const [historicalSources, setHistoricalSources] = useState<string[]>([]);
  const sources = sortSources(Array.from(new Set([...Object.keys(bySource), ...historicalSources])));
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [history, setHistory] = useState<CallEvent[]>([]);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyTotal, setHistoryTotal] = useState<number | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [highlightSeq, setHighlightSeq] = useState<number | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const highlightTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 이미 종료된 run(시험 이력에서 들어온 경우)은 라이브 WS 데이터가 더 이상
  // 없으므로, DB에 저장된 CallEvent만으로도 탭이 생기도록 마운트/run 전환
  // 시 한 번 소스 목록을 조회해둔다.
  useEffect(() => {
    if (!runId) {
      setHistoricalSources([]);
      return;
    }
    let cancelled = false;
    testRunsApi
      .getEvents(runId, { limit: JUMP_FETCH_LIMIT, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setHistoricalSources(Array.from(new Set(res.items.map((ev) => ev.source))));
      })
      .catch(() => {
        // 아직 조회할 로그가 없을 수 있음(신규 run) — 조용히 무시, 이후 WS 라이브 소스로 채워진다.
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

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

  // Call Flow에서 메시지 클릭 -> 해당 source 탭으로 전환하고 하이라이트 대상을 정한다.
  useEffect(() => {
    if (!jumpTarget) return;
    setActiveTab(jumpTarget.source);
    setHighlightSeq(jumpTarget.seqNo);
    clearJumpTarget();
    if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
    highlightTimeoutRef.current = setTimeout(() => setHighlightSeq(null), HIGHLIGHT_DURATION_MS);
  }, [jumpTarget, clearJumpTarget]);

  // 하이라이트 대상이 "과거 로그"에 아직 없으면 한 번 가져와서 채운다(행이
  // 실제로 나타나면 아래 ref 콜백이 스크롤을 맡는다).
  useEffect(() => {
    if (highlightSeq === null || !activeTab || !runId) return;
    if (history.some((ev) => ev.seq_no === highlightSeq)) return;

    let cancelled = false;
    testRunsApi
      .getEvents(runId, { limit: JUMP_FETCH_LIMIT, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        const found = res.items.filter((ev) => ev.source === activeTab);
        setHistory((prev) => {
          const known = new Set(prev.map((ev) => ev.id));
          return [...prev, ...found.filter((ev) => !known.has(ev.id))];
        });
        setHistoryTotal(res.total);
      })
      .catch(() => {
        // 조회 실패 시에도 하이라이트 자체는 타임아웃으로 알아서 사라진다 — 조용히 포기.
      });
    return () => {
      cancelled = true;
    };
    // history 배열 자체가 아니라 length로만 비교한다 — setHistory가 매번 새
    // 배열 참조를 만들기 때문에(내용이 안 바뀌어도) 전체 배열을 의존성에 넣으면
    // 이 effect가 자기 자신을 계속 재트리거하는 무한 루프가 된다(찾는 대상이
    // 없을 때 특히 심각 — 응답이 올 때마다 재요청을 반복해 브라우저가 멎어
    // 보일 정도로 부하가 걸렸다. "탭 전환 시 로그가 멈춘다"는 리포트의 원인).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightSeq, activeTab, runId, history.length]);

  useEffect(() => {
    return () => {
      if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
    };
  }, []);

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
            <div
              key={ev.id}
              ref={
                ev.seq_no === highlightSeq
                  ? (el) => el?.scrollIntoView({ block: "center", behavior: "smooth" })
                  : undefined
              }
              className={ev.seq_no === highlightSeq ? "log-line log-line-highlight" : "log-line"}
            >
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
