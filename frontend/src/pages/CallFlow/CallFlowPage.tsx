import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { testRunsApi } from "../../api/testRuns";
import type { CallFlowResponse } from "../../api/types";
import { MermaidDiagram } from "../../components/MermaidDiagram";
import "./CallFlowPage.css";

export function CallFlowPage() {
  const { runId = "" } = useParams<{ runId: string }>();
  const [callFlow, setCallFlow] = useState<CallFlowResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    // ASSUMED: GET /api/test-runs/{id}/call-flow — backend-agent 구현 중
    testRunsApi
      .getCallFlow(runId)
      .then((res) => {
        if (!cancelled) setCallFlow(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Call Flow 조회 실패");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  return (
    <div className="call-flow-page">
      <div className="page-header">
        <h2>Call Flow — {runId}</h2>
        <Link to={`/execution/${runId}`}>실행 화면으로</Link>
      </div>

      {loading && <div>Call Flow 불러오는 중...</div>}
      {error && <div className="page-error">{error}</div>}

      {callFlow && (
        <>
          <div className="call-flow-meta">생성 시각: {new Date(callFlow.generated_at).toLocaleString()}</div>
          <MermaidDiagram source={callFlow.mermaid_source} />
          <details>
            <summary>Mermaid 소스 보기</summary>
            <pre className="mermaid-source">{callFlow.mermaid_source}</pre>
          </details>
        </>
      )}

      {!loading && !error && !callFlow && <div>Call Flow 데이터가 없습니다.</div>}
    </div>
  );
}
