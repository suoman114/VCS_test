import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { healthApi } from "../../api/health";
import { testRunsApi } from "../../api/testRuns";
import type { HealthResponse, TestRun } from "../../api/types";
import { HealthBadge, StatusBadge } from "../../components/StatusBadge";
import "./DashboardPage.css";

const HEALTH_POLL_MS = 10000;

export function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [recentRuns, setRecentRuns] = useState<TestRun[]>([]);
  const [recentRunsError, setRecentRunsError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const res = await healthApi.check();
        if (!cancelled) {
          setHealth(res);
          setHealthError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setHealth(null);
          setHealthError(err instanceof Error ? err.message : "헬스체크 실패");
        }
      }
    }

    poll();
    const timer = setInterval(poll, HEALTH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    // ASSUMED: GET /api/test-runs — backend-agent 구현 중
    testRunsApi
      .list({ limit: 5, offset: 0 })
      .then((res) => {
        if (!cancelled) setRecentRuns(res.items);
      })
      .catch((err) => {
        if (!cancelled) setRecentRunsError(err instanceof Error ? err.message : "최근 실행 조회 실패");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="dashboard-page">
      <h2>대시보드</h2>

      <section className="health-section">
        <h3>연결 상태</h3>
        {healthError && <div className="page-error">백엔드 헬스체크 실패: {healthError}</div>}
        <div className="health-row">
          <HealthBadge ok={health ? health.status === "ok" : null} label="API 서버" />
          {/* TODO: VCS SSH / SIPp 헬스체크 필드는 아직 백엔드에 없다 (HealthResponse 확장 대기) */}
          <HealthBadge ok={health?.vcs_ssh ? health.vcs_ssh === "ok" : null} label="VCS SSH 연결" />
          <HealthBadge ok={health?.sipp ? health.sipp === "ok" : null} label="SIPp 실행 가능" />
        </div>
      </section>

      <section className="recent-runs-section">
        <h3>최근 시험 실행</h3>
        {recentRunsError && <div className="page-error">{recentRunsError}</div>}
        <ul className="recent-runs-list">
          {recentRuns.map((run) => (
            <li key={run.id}>
              <Link to={`/execution/${run.id}`}>{run.id}</Link>
              <span className="mono"> ({run.test_case_id})</span>
              <StatusBadge status={run.status} />
            </li>
          ))}
          {recentRuns.length === 0 && !recentRunsError && <li className="empty">최근 실행 이력이 없습니다.</li>}
        </ul>
        <Link to="/history">전체 이력 보기 →</Link>
      </section>

      <section className="quick-links">
        <Link to="/test-cases">시험 케이스 관리로 이동</Link>
      </section>
    </div>
  );
}
