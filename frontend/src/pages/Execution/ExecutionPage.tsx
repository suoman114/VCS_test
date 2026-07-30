import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../../api/client";
import { testRunsApi } from "../../api/testRuns";
import { useTestRunSocket } from "../../api/useTestRunSocket";
import type { CallFlowMessage, CallFlowResponse, TestRun, WsMessage } from "../../api/types";
import { useLogStore } from "../../store/logStore";
import { StatusBadge } from "../../components/StatusBadge";
import { LogViewer } from "../../components/LogViewer";
import { MermaidDiagram } from "../../components/MermaidDiagram";
import { ResultSummaryCard } from "../../components/ResultSummaryCard";
import "./ExecutionPage.css";

const POLL_INTERVAL_MS = 3000;
// Call Flow는 이제 WebSocket "call_flow" 메시지로 실시간 push된다(execution_common
// .persist_call_flow/persist_results). 아래 폴링은 최초 진입 시(WS 연결 전
// 과거 run 진입 등) 및 메시지 유실 대비 fallback일 뿐이라 간격을 넉넉히 둔다.
const CALL_FLOW_POLL_INTERVAL_MS = 15000;
const TERMINAL_STATUSES = new Set(["done", "failed", "error"]);
// McPTT 성능 시험처럼 -m(총 호 수) 없이 무기한 실행되는 시험은 이 상태들에서
// "종료" 버튼이 유일한 정상 종료 경로다(2026-07-30) — 기본 호처리 시험도
// 중간에 멈추고 싶을 수 있어 프로토콜/유형 구분 없이 진행 중이면 항상 보여준다.
const CANCELLABLE_STATUSES = new Set(["pending", "running", "parsing"]);

export function ExecutionPage() {
  const { runId = null } = useParams<{ runId: string }>();
  const [run, setRun] = useState<TestRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const setActiveRunId = useLogStore((s) => s.setActiveRunId);
  const appendLine = useLogStore((s) => s.appendLine);
  const setSourceError = useLogStore((s) => s.setSourceError);
  const setLiveStatus = useLogStore((s) => s.setLiveStatus);
  const liveStatus = useLogStore((s) => s.liveStatus);
  const setJumpTarget = useLogStore((s) => s.setJumpTarget);

  const [callFlow, setCallFlow] = useState<CallFlowResponse | null>(null);
  const callFlowPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // McPTT 성능 시험처럼 한 Test Run에 콜이 여러 건 섞이는 경우 Call Flow를
  // call_id 단위로 골라볼 수 있게 한다(2026-07-30 추가). null이면 "전체".
  const [callIds, setCallIds] = useState<string[]>([]);
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);

  const fetchCallIds = useCallback(async () => {
    if (!runId) return;
    try {
      const data = await testRunsApi.getCallIds(runId);
      setCallIds(data.items);
    } catch {
      // 아직 이벤트가 없을 수 있음 — 조용히 무시(드롭다운은 "전체"만 노출).
    }
  }, [runId]);

  // 주 경로는 WebSocket "call_flow" push(handleWsMessage)다. 이 REST 호출은
  // 최초 로드(WS 연결 완료 전에 이미 일부 진행된 run에 들어온 경우)와
  // fallback, 그리고 call_id 필터를 바꿨을 때 그 콜만 다시 가져오는 데 쓰인다.
  // 아직 생성 전이면 404가 정상이라 화면 상단 에러로는 띄우지 않는다.
  const fetchCallFlow = useCallback(async () => {
    if (!runId) return;
    try {
      const data = await testRunsApi.getCallFlow(runId, selectedCallId ?? undefined);
      setCallFlow(data);
    } catch {
      // 아직 생성되지 않았을 수 있음(진행 중) — 조용히 무시하고 다음 폴링을 기다린다.
    }
  }, [runId, selectedCallId]);

  const handleWsMessage = useCallback(
    (msg: WsMessage) => {
      if (msg.type === "log") {
        appendLine(msg.source, { seq: msg.seq, source: msg.source, line: msg.line, ts: msg.ts });
      } else if (msg.type === "log_source_error") {
        setSourceError(msg.source, msg.message);
      } else if (msg.type === "status") {
        setLiveStatus(msg.status);
      } else if (msg.type === "call_flow") {
        // WS push는 항상 필터 없는 전체 Call Flow다(execution_common
        // .persist_call_flow는 call_id 필터를 모른다). "전체" 보기 중이면
        // 그대로 반영하고, 특정 콜로 필터링 중이면 그 콜만 REST로 다시
        // 가져온다 — 성능 시험은 콜이 계속 늘어나므로 목록도 같이 새로고침.
        if (selectedCallId === null) {
          setCallFlow({
            run_id: msg.run_id,
            mermaid_source: msg.mermaid_source,
            generated_at: msg.generated_at,
            messages: msg.messages,
          });
        } else {
          fetchCallFlow();
        }
        fetchCallIds();
      }
    },
    [appendLine, setSourceError, setLiveStatus, selectedCallId, fetchCallFlow, fetchCallIds],
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
      // 404는 백엔드가 "TestRun not found"라는 영문 메시지를 그대로 내려줘서
      // 화면 전체가 한글인데 이 문구만 영문으로 보이던 문제(2026-07-30 발견)
      // — 존재하지 않는 run을 명시적으로 구분해 한글 메시지로 보여준다.
      if (err instanceof ApiError && err.status === 404) {
        setError(`Test Run을 찾을 수 없습니다 (ID: ${runId}).`);
      } else {
        setError(err instanceof Error ? err.message : "Test Run 조회 실패");
      }
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

  const handleCancel = useCallback(async () => {
    if (!runId) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await testRunsApi.cancel(runId);
      // 상태 갱신은 백엔드에서 비동기로 이루어진다(202) — 폴링 주기를 기다리지
      // 않고 바로 한 번 더 조회해서 화면 반영을 앞당긴다. 폴링이 이미 멈춰
      // 있었다면(예전 상태가 이미 terminal이었던 특이 케이스) 다시 켠다.
      await fetchRun();
      if (!pollRef.current) {
        pollRef.current = setInterval(fetchRun, POLL_INTERVAL_MS);
      }
    } catch (err) {
      setCancelError(err instanceof ApiError ? err.message : "종료 요청 실패");
    } finally {
      setCancelling(false);
    }
  }, [runId, fetchRun]);

  // runId가 바뀌면(다른 Test Run으로 이동) Call Flow 상태를 전부 초기화한다
  // (call_id 필터는 이전 run에서 고른 값이 남아있으면 안 되므로 같이 리셋).
  useEffect(() => {
    setCallFlow(null);
    setCallIds([]);
    setSelectedCallId(null);
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    fetchCallFlow();
    fetchCallIds();
    callFlowPollRef.current = setInterval(() => {
      fetchCallFlow();
      fetchCallIds();
    }, CALL_FLOW_POLL_INTERVAL_MS);
    return () => {
      if (callFlowPollRef.current) clearInterval(callFlowPollRef.current);
    };
  }, [runId, fetchCallFlow, fetchCallIds]);

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

  // run을 한 번도 못 불러왔으면(존재하지 않는 run_id 등) 로그/Call Flow처럼
  // 빈 UI를 그대로 렌더링하지 않는다 — 예전엔 "TestRun not found" 에러
  // 배너 아래로 빈 로그 패널/Call Flow 영역이 정상 화면처럼 계속 보여서
  // 혼란스러웠다(2026-07-30 발견). 이미 한 번 로드된 뒤 폴링이 일시적으로
  // 실패한 경우는 run이 이미 채워져 있으므로 이 분기를 타지 않는다.
  if (!run && error) {
    return (
      <div className="execution-page">
        <div className="page-header">
          <h2>시험 실행</h2>
        </div>
        <div className="page-error">{error}</div>
        <div className="execution-links">
          <Link to="/history">시험 이력으로 이동</Link>
        </div>
      </div>
    );
  }

  const displayStatus = liveStatus ?? run?.status ?? null;

  return (
    <div className="execution-page">
      <div className="page-header">
        <h2>시험 실행 — {run?.test_case_name ?? runId}</h2>
        <StatusBadge status={displayStatus} />
        {displayStatus && CANCELLABLE_STATUSES.has(displayStatus) && (
          <button type="button" className="cancel-run-button" onClick={handleCancel} disabled={cancelling}>
            {cancelling ? "종료 요청 중..." : "시험 종료"}
          </button>
        )}
      </div>

      {error && <div className="page-error">{error}</div>}
      {cancelError && <div className="page-error">{cancelError}</div>}

      <div className="run-meta">
        <div>
          <strong>Test Case</strong>: {run?.test_case_name ?? run?.test_case_id ?? "-"}
        </div>
        <div>
          <strong>Run ID</strong>: <span className="mono">{runId}</span>
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
        <div className="result-summary-section">
          <h3>결과 요약</h3>
          <ResultSummaryCard resultSummary={run.result_summary} />
        </div>
      )}

      <div className="execution-split">
        <div className="execution-split-log">
          <h3>실시간 로그</h3>
          <div className="split-column-meta">프로세스별 실시간 스트림과 과거 로그를 확인합니다.</div>
          <LogViewer runId={runId} />
        </div>

        <div className="call-flow-section">
          <h3>Call Flow</h3>
          {callIds.length > 0 && (
            <div className="call-flow-filter">
              <label>
                콜 선택:{" "}
                <select
                  value={selectedCallId ?? ""}
                  onChange={(e) => setSelectedCallId(e.target.value === "" ? null : e.target.value)}
                >
                  <option value="">전체 ({callIds.length}건)</option>
                  {callIds.map((callId) => (
                    <option key={callId} value={callId}>
                      {callId}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
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
        <Link to={`/report/${runId}`}>리포트 보기</Link>
      </div>
    </div>
  );
}
