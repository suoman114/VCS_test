import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { testRunsApi } from "../../api/testRuns";
import { useTestRunSocket } from "../../api/useTestRunSocket";
import type { CallFlowMessage, CallFlowResponse, TestRun, WsMessage } from "../../api/types";
import { useLogStore } from "../../store/logStore";
import { StatusBadge } from "../../components/StatusBadge";
import { LogViewer } from "../../components/LogViewer";
import { MermaidDiagram } from "../../components/MermaidDiagram";
import "./ExecutionPage.css";

const POLL_INTERVAL_MS = 3000;
// Call Flow는 이제 WebSocket "call_flow" 메시지로 실시간 push된다(execution_common
// .persist_call_flow/persist_results). 아래 폴링은 최초 진입 시(WS 연결 전
// 과거 run 진입 등) 및 메시지 유실 대비 fallback일 뿐이라 간격을 넉넉히 둔다.
const CALL_FLOW_POLL_INTERVAL_MS = 15000;
const TERMINAL_STATUSES = new Set(["done", "failed", "error"]);

export function ExecutionPage() {
  const { runId = null } = useParams<{ runId: string }>();
  const [run, setRun] = useState<TestRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const setActiveRunId = useLogStore((s) => s.setActiveRunId);
  const appendLine = useLogStore((s) => s.appendLine);
  const setSourceError = useLogStore((s) => s.setSourceError);
  const setLiveStatus = useLogStore((s) => s.setLiveStatus);
  const liveStatus = useLogStore((s) => s.liveStatus);
  const setJumpTarget = useLogStore((s) => s.setJumpTarget);

  const [callFlow, setCallFlow] = useState<CallFlowResponse | null>(null);
  const callFlowPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleWsMessage = useCallback(
    (msg: WsMessage) => {
      if (msg.type === "log") {
        appendLine(msg.source, { seq: msg.seq, source: msg.source, line: msg.line, ts: msg.ts });
      } else if (msg.type === "log_source_error") {
        setSourceError(msg.source, msg.message);
      } else if (msg.type === "status") {
        setLiveStatus(msg.status);
      } else if (msg.type === "call_flow") {
        setCallFlow({
          run_id: msg.run_id,
          mermaid_source: msg.mermaid_source,
          generated_at: msg.generated_at,
          messages: msg.messages,
        });
      }
    },
    [appendLine, setSourceError, setLiveStatus],
  );

  // Call Flow에서 메시지(INVITE/100/180 등)를 클릭하면 로그 뷰어가 해당
  // source 탭으로 전환하고 그 줄로 스크롤+하이라이트한다(components/LogViewer.tsx).
  const handleCallFlowMessageClick = useCallback(
    (message: CallFlowMessage) => {
      setJumpTarget({ source: message.source, seqNo: message.seq_no });
    },
    [setJumpTarget],
  );

  // ASSUMED: WebSocket 경로/메시지 상세는 backend-agent 최종 구현에서 바뀔 수 있다 (api/useTestRunSocket.ts 참고)
  const { status: wsStatus } = useTestRunSocket(runId, handleWsMessage);

  useEffect(() => {
    setActiveRunId(runId);
    return () => setActiveRunId(null);
  }, [runId, setActiveRunId]);

  const fetchRun = useCallback(async () => {
    if (!runId) return;
    try {
      const data = await testRunsApi.get(runId);
      setRun(data);
      setError(null);
      if (TERMINAL_STATUSES.has(data.status) && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test Run 조회 실패");
    }
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    fetchRun();
    pollRef.current = setInterval(fetchRun, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [runId, fetchRun]);

  // 주 경로는 WebSocket "call_flow" push(handleWsMessage)다. 이 REST 폴링은
  // 최초 로드(WS 연결 완료 전에 이미 일부 진행된 run에 들어온 경우)와
  // fallback용이다. 아직 생성 전이면 404가 정상이라 화면 상단 에러로는
  // 띄우지 않고 "아직 생성되지 않음"으로만 표시한다.
  const fetchCallFlow = useCallback(async () => {
    if (!runId) return;
    try {
      const data = await testRunsApi.getCallFlow(runId);
      setCallFlow(data);
    } catch {
      // 아직 생성되지 않았을 수 있음(진행 중) — 조용히 무시하고 다음 폴링을 기다린다.
    }
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    setCallFlow(null);
    fetchCallFlow();
    callFlowPollRef.current = setInterval(fetchCallFlow, CALL_FLOW_POLL_INTERVAL_MS);
    return () => {
      if (callFlowPollRef.current) clearInterval(callFlowPollRef.current);
    };
  }, [runId, fetchCallFlow]);

  useEffect(() => {
    if (run && TERMINAL_STATUSES.has(run.status) && callFlowPollRef.current) {
      fetchCallFlow(); // 종료 직후 마지막 상태를 한 번 더 확실히 받아온다.
      clearInterval(callFlowPollRef.current);
      callFlowPollRef.current = null;
    }
  }, [run, fetchCallFlow]);

  if (!runId) {
    return (
      <div className="execution-page">
        <h2>시험 실행</h2>
        <p>시험 케이스 관리 화면에서 케이스를 실행하면 이 화면으로 이동합니다.</p>
        <Link to="/test-cases">시험 케이스 관리로 이동</Link>
      </div>
    );
  }

  const displayStatus = liveStatus ?? run?.status ?? null;

  return (
    <div className="execution-page">
      <div className="page-header">
        <h2>시험 실행 — {runId}</h2>
        <StatusBadge status={displayStatus} />
      </div>

      {error && <div className="page-error">{error}</div>}

      <div className="run-meta">
        <div>
          <strong>Test Case</strong>: {run?.test_case_id ?? "-"}
        </div>
        <div>
          <strong>대상 호스트</strong>: {run?.target_host ?? "-"}
        </div>
        <div>
          <strong>시작</strong>: {run?.started_at ? new Date(run.started_at).toLocaleString() : "-"}
        </div>
        <div>
          <strong>종료</strong>: {run?.ended_at ? new Date(run.ended_at).toLocaleString() : "-"}
        </div>
        <div>
          <strong>WebSocket</strong>: {wsStatus}
        </div>
      </div>

      {run?.result_summary && (
        <details className="result-summary">
          <summary>결과 요약</summary>
          <pre>{JSON.stringify(run.result_summary, null, 2)}</pre>
        </details>
      )}

      <div className="execution-split">
        <div className="execution-split-log">
          <h3>실시간 로그</h3>
          <div className="split-column-meta">프로세스별 실시간 스트림과 과거 로그를 확인합니다.</div>
          <LogViewer runId={runId} />
        </div>

        <div className="call-flow-section">
          <h3>Call Flow</h3>
          <div className="split-column-meta">
            {callFlow
              ? `생성 시각: ${new Date(callFlow.generated_at).toLocaleString()} · 메시지를 클릭하면 왼쪽 로그에서 해당 줄로 이동합니다.`
              : " "}
          </div>
          {callFlow ? (
            <MermaidDiagram
              source={callFlow.mermaid_source}
              messages={callFlow.messages}
              onMessageClick={handleCallFlowMessageClick}
            />
          ) : (
            <div className="log-empty">
              {run && TERMINAL_STATUSES.has(run.status)
                ? "Call Flow 데이터가 없습니다."
                : "아직 생성되지 않았습니다 (진행 중이면 로그 수신에 따라 갱신됩니다)."}
            </div>
          )}
        </div>
      </div>

      <div className="execution-links">
        <Link to="/history">시험 이력으로 이동</Link>
      </div>
    </div>
  );
}
