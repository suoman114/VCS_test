import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { testRunsApi } from "../../api/testRuns";
import type { TestRun, TestRunStatus } from "../../api/types";
import { StatusBadge } from "../../components/StatusBadge";
import "./HistoryPage.css";

const PAGE_SIZE = 20;

export function HistoryPage() {
  const [items, setItems] = useState<TestRun[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<TestRunStatus | "">("");
  const [testCaseIdFilter, setTestCaseIdFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // ASSUMED: GET /api/test-runs — backend-agent 구현 중 (api/testRuns.ts 참고)
      const res = await testRunsApi.list({
        status: statusFilter || undefined,
        test_case_id: testCaseIdFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "이력 조회 실패");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, testCaseIdFilter, offset]);

  useEffect(() => {
    load();
  }, [load]);

  const stats = useMemo(() => {
    const passed = items.filter((r) => r.status === "done").length;
    const failed = items.filter((r) => r.status === "failed" || r.status === "error").length;
    const inProgress = items.filter((r) => r.status === "pending" || r.status === "running" || r.status === "parsing").length;
    return { passed, failed, inProgress, total: items.length };
  }, [items]);

  return (
    <div className="history-page">
      <h2>시험 이력</h2>

      <div className="stats-row">
        <div className="stat-card stat-done">
          <div className="stat-value">{stats.passed}</div>
          <div className="stat-label">Pass (현재 페이지)</div>
        </div>
        <div className="stat-card stat-failed">
          <div className="stat-value">{stats.failed}</div>
          <div className="stat-label">Fail (현재 페이지)</div>
        </div>
        <div className="stat-card stat-progress">
          <div className="stat-value">{stats.inProgress}</div>
          <div className="stat-label">진행중 (현재 페이지)</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{total}</div>
          <div className="stat-label">전체 Test Run</div>
        </div>
      </div>
      <p className="stats-note">
        참고: Pass/Fail 통계는 현재 페이지에 로드된 항목 기준입니다. 백엔드에 집계 API가 추가되면 전체 통계로 교체합니다.
      </p>

      <div className="filters">
        <select
          value={statusFilter}
          onChange={(e) => {
            setOffset(0);
            setStatusFilter(e.target.value as TestRunStatus | "");
          }}
        >
          <option value="">전체 상태</option>
          <option value="pending">pending</option>
          <option value="running">running</option>
          <option value="parsing">parsing</option>
          <option value="done">done</option>
          <option value="failed">failed</option>
          <option value="error">error</option>
        </select>

        <input
          placeholder="Test Case ID 검색"
          value={testCaseIdFilter}
          onChange={(e) => {
            setOffset(0);
            setTestCaseIdFilter(e.target.value);
          }}
        />
      </div>

      {error && <div className="page-error">{error}</div>}

      {loading ? (
        <div>불러오는 중...</div>
      ) : (
        <table className="history-table">
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Test Case</th>
              <th>상태</th>
              <th>시작</th>
              <th>종료</th>
              <th>대상 호스트</th>
              <th>조회</th>
            </tr>
          </thead>
          <tbody>
            {items.map((run) => (
              <tr key={run.id}>
                <td className="mono">{run.id}</td>
                <td className="mono">{run.test_case_id}</td>
                <td>
                  <StatusBadge status={run.status} />
                </td>
                <td>{run.started_at ? new Date(run.started_at).toLocaleString() : "-"}</td>
                <td>{run.ended_at ? new Date(run.ended_at).toLocaleString() : "-"}</td>
                <td>{run.target_host ?? "-"}</td>
                <td className="actions">
                  <Link to={`/execution/${run.id}`}>로그</Link>
                  <Link to={`/call-flow/${run.id}`}>Call Flow</Link>
                  <Link to={`/report/${run.id}`}>리포트</Link>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={7} className="empty-row">
                  Test Run 이력이 없습니다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      <div className="pagination">
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          이전
        </button>
        <span>
          {offset + 1}-{Math.min(offset + PAGE_SIZE, total)} / {total}
        </span>
        <button disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
          다음
        </button>
      </div>
    </div>
  );
}
