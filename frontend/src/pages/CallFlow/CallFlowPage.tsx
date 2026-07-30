import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../../api/client";
import { testRunsApi } from "../../api/testRuns";
import type { CallFlowResponse } from "../../api/types";
import { MermaidDiagram } from "../../components/MermaidDiagram";
import "./CallFlowPage.css";

export function CallFlowPage() {
  const { runId = "" } = useParams<{ runId: string }>();
  const [testCaseName, setTestCaseName] = useState<string | null>(null);
  const [callFlow, setCallFlow] = useState<CallFlowResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    testRunsApi
      .get(runId)
      .then((run) => {
        if (!cancelled) setTestCaseName(run.test_case_name);
      })
      .catch(() => {
        // 제목 보조 정보일 뿐이라 실패해도 조용히 무시 — 아래 Call Flow 조회
        // 결과/에러가 이 페이지의 주 상태를 결정한다.
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    testRunsApi
      .getCallFlow(runId)
      .then((res) => {
        if (!cancelled) setCallFlow(res);
      })
      .catch((err) => {
        if (cancelled) return;
        // 아직 생성 전(404)은 에러가 아니라 정상적인 "진행 중" 상태다 — 백엔드가
        // 내려주는 영문 상세 메시지("Call flow not generated yet...")를 그대로
        // 빨간 에러 배너로 노출하지 않는다(2026-07-30 발견, ExecutionPage의
        // fetchCallFlow와 동일하게 조용히 빈 상태로 처리).
        if (err instanceof ApiError && err.status === 404) {
          setCallFlow(null);
        } else {
          setError(err instanceof Error ? err.message : "Call Flow 조회 실패");
        }
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
        <h2>Call Flow — {testCaseName ?? runId}</h2>
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
