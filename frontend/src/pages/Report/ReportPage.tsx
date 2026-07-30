/**
 * Test Run 리포트 페이지 (2026-07-30 추가) — PDF 저장은 브라우저 인쇄
 * 기능(Ctrl+P / "인쇄" 버튼)에 맡긴다. 별도 PDF 렌더링 서버/의존성을 새로
 * 추가하지 않는 대신, 인쇄 시 상단 내비게이션을 숨기고(App.css) 한 페이지에
 * 정보가 잘 들어오도록 print 전용 스타일을 둔다.
 *
 * 콜 설정 시간 분포/시간별 동시 통화 수(`report-stats`)는 성능 시험처럼
 * recording_start_req/res, recording_stop_res 이벤트가 있을 때만 의미가
 * 있다 — 데이터가 없으면(`setup_time`이 null, `concurrency_series`가 빈
 * 배열) 그 섹션 자체를 렌더링하지 않는다(기본 호처리 시험 리포트에는
 * 안 보이는 게 정상).
 *
 * Call Flow는 필터 없는 전체 다이어그램 대신 첫 번째 call_id 하나만
 * 대표로 보여준다(2026-07-30 요청) — 성능 시험은 같은 시나리오를 반복
 * 실행하는 것이라 콜마다 흐름이 사실상 동일하고, 모든 콜을 한 다이어그램에
 * 합치면(ExecutionPage에 call_id 필터를 추가했던 바로 그 이유) 리포트에서도
 * 똑같이 못 읽는 그림이 된다. call_id가 하나도 없으면(레거시 데이터 등)
 * 전체 다이어그램으로 폴백한다.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { testCasesApi } from "../../api/testCases";
import { testRunsApi } from "../../api/testRuns";
import type { CallFlowResponse, ReportStatsResponse, TestCaseRead, TestRun } from "../../api/types";
import { StatusBadge } from "../../components/StatusBadge";
import { MermaidDiagram } from "../../components/MermaidDiagram";
import { ResultSummaryCard } from "../../components/ResultSummaryCard";
import { ConcurrencyChart, SetupTimeHistogramChart } from "../../components/ReportCharts";
import "./ReportPage.css";

export function ReportPage() {
  const { runId = "" } = useParams<{ runId: string }>();
  const [run, setRun] = useState<TestRun | null>(null);
  const [testCase, setTestCase] = useState<TestCaseRead | null>(null);
  const [callFlow, setCallFlow] = useState<CallFlowResponse | null>(null);
  const [callFlowCallId, setCallFlowCallId] = useState<string | null>(null);
  const [totalCallCount, setTotalCallCount] = useState(0);
  const [reportStats, setReportStats] = useState<ReportStatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const runData = await testRunsApi.get(runId);
        if (cancelled) return;
        setRun(runData);

        // report-stats는 리포트 화면 진입 시에만 호출한다 — 라이브 폴링 금지(계산 비용 때문).
        const [testCaseData, reportStatsData, callIdsData] = await Promise.all([
          testCasesApi.get(runData.test_case_id).catch(() => null),
          testRunsApi.getReportStats(runId).catch(() => null),
          testRunsApi.getCallIds(runId).catch(() => null),
        ]);
        if (cancelled) return;
        setTestCase(testCaseData);
        setReportStats(reportStatsData);

        const callIds = callIdsData?.items ?? [];
        setTotalCallCount(callIds.length);
        // 대표로 첫 콜 하나만 보여준다(모듈 docstring 참고) — call_id가 없으면
        // (레거시 데이터 등) 필터 없는 전체 다이어그램으로 폴백한다.
        const representativeCallId = callIds[0] ?? null;
        setCallFlowCallId(representativeCallId);
        const callFlowData = await testRunsApi
          .getCallFlow(runId, representativeCallId ?? undefined)
          .catch(() => null);
        if (cancelled) return;
        setCallFlow(callFlowData);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "리포트 데이터를 불러오지 못했습니다");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [runId]);

  return (
    <div className="report-page">
      <div className="report-page-toolbar">
        <Link to={`/execution/${runId}`}>실행 화면으로</Link>
        <button type="button" onClick={() => window.print()}>
          인쇄 / PDF로 저장
        </button>
      </div>

      {loading && <div>리포트를 불러오는 중...</div>}
      {error && <div className="page-error">{error}</div>}

      {run && (
        <div className="report-content">
          <header className="report-header">
            <h1>{testCase?.name ?? "시험 리포트"}</h1>
            <StatusBadge status={run.status} />
          </header>

          <section className="report-section">
            <h2>시험 개요</h2>
            <dl className="report-meta-grid">
              <dt>Test Run ID</dt>
              <dd>{run.id}</dd>
              <dt>프로토콜 / 유형</dt>
              <dd>
                {testCase ? `${testCase.category.toUpperCase()} / ${testCase.test_type}` : "-"}
              </dd>
              <dt>설정</dt>
              <dd>{testCase?.config_ref ?? "-"}</dd>
              <dt>대상 호스트</dt>
              <dd>{run.target_host ?? "-"}</dd>
              <dt>시작</dt>
              <dd>{run.started_at ? new Date(run.started_at).toLocaleString() : "-"}</dd>
              <dt>종료</dt>
              <dd>{run.ended_at ? new Date(run.ended_at).toLocaleString() : "-"}</dd>
            </dl>
          </section>

          {run.result_summary && (
            <section className="report-section">
              <h2>결과 요약</h2>
              <ResultSummaryCard resultSummary={run.result_summary} />
            </section>
          )}

          {reportStats?.setup_time && (
            <section className="report-section report-avoid-break">
              <h2>콜 설정 시간 분포</h2>
              <p className="report-section-note">
                녹취 개시 소요시간(recording_start_req ~ res) 기준입니다. SIP 통화 연결 시간이 아닙니다.
              </p>
              <div className="report-stat-row">
                <span>표본 {reportStats.setup_time.count}건</span>
                <span>최소 {reportStats.setup_time.min_ms}ms</span>
                <span>평균 {reportStats.setup_time.avg_ms}ms</span>
                <span>p50 {reportStats.setup_time.p50_ms}ms</span>
                <span>p95 {reportStats.setup_time.p95_ms}ms</span>
                <span>최대 {reportStats.setup_time.max_ms}ms</span>
              </div>
              <SetupTimeHistogramChart histogram={reportStats.setup_time.histogram} />
            </section>
          )}

          {reportStats && reportStats.concurrency_series.length > 0 && (
            <section className="report-section report-avoid-break">
              <h2>시간별 동시 통화 수</h2>
              <p className="report-section-note">{reportStats.bucket_seconds}초 단위 버킷입니다.</p>
              <ConcurrencyChart series={reportStats.concurrency_series} />
            </section>
          )}

          <section className="report-section report-avoid-break">
            <h2>Call Flow</h2>
            {callFlowCallId && totalCallCount > 1 && (
              <p className="report-section-note">
                대표 콜 1건({callFlowCallId})의 흐름입니다. 총 {totalCallCount}개 콜이 동일한 시나리오를
                반복합니다 — 콜별로 따로 보려면{" "}
                <Link to={`/execution/${runId}`}>실행 화면</Link>의 "콜 선택" 드롭다운을 사용하세요.
              </p>
            )}
            {callFlow ? (
              <MermaidDiagram source={callFlow.mermaid_source} />
            ) : (
              <div className="report-section-note">Call Flow 데이터가 없습니다.</div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
