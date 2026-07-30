/**
 * TestRun.result_summary(JSON 문자열)를 사람이 읽기 좋은 카드로 렌더링한다.
 *
 * 백엔드가 실제로 내려주는 두 가지 형태(app/services/{volte,mcptt}/executor.py,
 * app/job_runner/runner.py):
 *   - 정상 종료: {passed, reasons, timed_out, event_count, sipp_exit_status?}
 *   - 인프라 예외(job_runner._run_wrapper): {error}
 * 두 형태 모두 아닌 값(형식이 안 맞는 예외적인 경우)이거나 파싱 자체가
 * 실패하면 원본 문자열을 그대로 보여준다 — 정보를 숨기지 않는다.
 */
import { useState } from "react";
import "./ResultSummaryCard.css";

interface SuccessSummary {
  passed: boolean;
  reasons?: string[];
  timed_out?: boolean;
  event_count?: number;
  sipp_exit_status?: number | null;
}

interface ErrorSummary {
  error: string;
}

function isErrorSummary(v: unknown): v is ErrorSummary {
  return typeof v === "object" && v !== null && typeof (v as ErrorSummary).error === "string";
}

function isSuccessSummary(v: unknown): v is SuccessSummary {
  return typeof v === "object" && v !== null && typeof (v as SuccessSummary).passed === "boolean";
}

function prettyJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

export function ResultSummaryCard({ resultSummary }: { resultSummary: string }) {
  const [showRaw, setShowRaw] = useState(false);

  let parsed: unknown;
  try {
    parsed = JSON.parse(resultSummary);
  } catch {
    parsed = null;
  }

  const rawToggle = (
    <button type="button" className="result-raw-toggle" onClick={() => setShowRaw((v) => !v)}>
      {showRaw ? "원본 JSON 숨기기" : "원본 JSON 보기"}
    </button>
  );
  const rawBlock = showRaw && <pre className="result-raw">{prettyJson(resultSummary)}</pre>;

  if (isErrorSummary(parsed)) {
    return (
      <div className="result-card result-card-error">
        <div className="result-card-header">
          <span className="result-pill result-pill-error">인프라 오류</span>
        </div>
        <div className="result-error-message">{parsed.error}</div>
        {rawToggle}
        {rawBlock}
      </div>
    );
  }

  if (isSuccessSummary(parsed)) {
    const reasons = parsed.reasons ?? [];
    return (
      <div className={parsed.passed ? "result-card result-card-pass" : "result-card result-card-fail"}>
        <div className="result-card-header">
          <span className={parsed.passed ? "result-pill result-pill-pass" : "result-pill result-pill-fail"}>
            {parsed.passed ? "PASS" : "FAIL"}
          </span>
          {parsed.timed_out && <span className="result-pill result-pill-warn">타임아웃</span>}
          {typeof parsed.event_count === "number" && (
            <span className="result-meta">이벤트 {parsed.event_count}건</span>
          )}
          {parsed.sipp_exit_status !== undefined && parsed.sipp_exit_status !== null && (
            <span className="result-meta">
              SIPp 종료 코드 {parsed.sipp_exit_status}
              {parsed.sipp_exit_status !== 0 && " (비정상)"}
            </span>
          )}
        </div>
        {reasons.length > 0 && (
          <ul className="result-reasons">
            {reasons.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
        )}
        {rawToggle}
        {rawBlock}
      </div>
    );
  }

  // 알려진 두 형태 모두 아님 — 원본을 그대로 보여준다.
  return (
    <div className="result-card">
      <pre className="result-raw">{prettyJson(resultSummary)}</pre>
    </div>
  );
}
