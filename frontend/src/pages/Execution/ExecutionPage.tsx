import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { testRunsApi } from "../../api/testRuns";
import { useTestRunSocket } from "../../api/useTestRunSocket";
import type { TestRun, WsMessage } from "../../api/types";
import { useLogStore } from "../../store/logStore";
import { StatusBadge } from "../../components/StatusBadge";
import { LogViewer } from "../../components/LogViewer";
import "./ExecutionPage.css";

const POLL_INTERVAL_MS = 3000;
const TERMINAL_STATUSES = new Set(["done", "failed", "error"]);

export function ExecutionPage() {
  const { runId = null } = useParams<{ runId: string }>();
  const [run, setRun] = useState<TestRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const setActiveRunId = useLogStore((s) => s.setActiveRunId);
  const appendLine = useLogStore((s) => s.appendLine);
  const setChannelError = useLogStore((s) => s.setChannelError);
  const setLiveStatus = useLogStore((s) => s.setLiveStatus);
  const liveStatus = useLogStore((s) => s.liveStatus);

  const handleWsMessage = useCallback(
    (msg: WsMessage) => {
      if (msg.type === "log") {
        appendLine(msg.channel, { seq: msg.seq, source: msg.source, line: msg.line, ts: msg.ts });
      } else if (msg.type === "log_source_error") {
        setChannelError(msg.channel === "sipp_log" ? "sipp_log" : "vcs_log", msg.message);
      } else if (msg.type === "status") {
        setLiveStatus(msg.status);
      }
    },
    [appendLine, setChannelError, setLiveStatus],
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

      <LogViewer runId={runId} />

      <div className="execution-links">
        <Link to={`/call-flow/${runId}`}>Call Flow 보기 →</Link>
        <Link to="/history">시험 이력으로 이동</Link>
      </div>
    </div>
  );
}
