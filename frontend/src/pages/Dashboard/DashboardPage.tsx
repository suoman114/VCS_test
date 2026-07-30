import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { healthApi } from "../../api/health";
import { testRunsApi } from "../../api/testRuns";
import type { HealthResponse, TestCaseCategory, TestRun, TestRunStatsBucket, TestRunStatsResponse } from "../../api/types";
import { HealthBadge, StatusBadge } from "../../components/StatusBadge";
import "./DashboardPage.css";

const HEALTH_POLL_MS = 10000;
const STATS_POLL_MS = 30000;

const CATEGORY_LABEL: Record<TestCaseCategory, string> = {
  volte: "VoLTE",
  mcptt: "McPTT",
};

function formatPassRate(rate: number | null): string {
  return rate === null ? "-" : `${Math.round(rate * 100)}%`;
}

/** Pass율 숫자 색상: 데이터가 없으면 회색, 70% 미만은 주의 색으로 눈에 띄게 한다. */
function passRateClass(rate: number | null): string {
  if (rate === null) return "stat-value stat-value-muted";
  if (rate < 0.7) return "stat-value stat-value-warn";
  return "stat-value stat-value-good";
}

function StatBucketCard({ title, bucket }: { title: string; bucket: TestRunStatsBucket }) {
  return (
    <div className="stat-card">
      <div className={passRateClass(bucket.pass_rate)}>{formatPassRate(bucket.pass_rate)}</div>
      <div className="stat-label">{title} Pass율</div>
      <div className="stat-breakdown">
        <span className="stat-chip stat-chip-done">Pass {bucket.passed}</span>
        <span className="stat-chip stat-chip-failed">Fail {bucket.failed}</span>
        <span className="stat-chip stat-chip-error">Error {bucket.error}</span>
        {bucket.in_progress > 0 && <span className="stat-chip stat-chip-progress">진행중 {bucket.in_progress}</span>}
      </div>
    </div>
  );
}

export function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [recentRuns, setRecentRuns] = useState<TestRun[]>([]);
  const [recentRunsError, setRecentRunsError] = useState<string | null>(null);
  const [stats, setStats] = useState<TestRunStatsResponse | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);

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

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const res = await testRunsApi.getStats();
        if (!cancelled) {
          setStats(res);
          setStatsError(null);
        }
      } catch (err) {
        if (!cancelled) setStatsError(err instanceof Error ? err.message : "통계 조회 실패");
      }
    }

    poll();
    const timer = setInterval(poll, STATS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
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

      <section className="stats-section">
        <h3>시험 통계</h3>
        {statsError && <div className="page-error">통계 조회 실패: {statsError}</div>}
        {stats && (
          <>
            <div className="stats-row">
              <StatBucketCard title="전체" bucket={stats.overall} />
              <StatBucketCard title={`최근 ${stats.recent_days}일`} bucket={stats.recent} />
              {(Object.keys(stats.by_category) as TestCaseCategory[]).map((category) => (
                <StatBucketCard
                  key={category}
                  title={CATEGORY_LABEL[category] ?? category}
                  bucket={stats.by_category[category]!}
                />
              ))}
            </div>
            {Object.keys(stats.by_category).length === 0 && (
              <div className="stats-note">아직 실행된 시험이 없습니다.</div>
            )}
          </>
        )}
        {!stats && !statsError && <div className="stats-note">불러오는 중...</div>}
      </section>

      <section className="recent-runs-section">
        <h3>최근 시험 실행</h3>
        {recentRunsError && <div className="page-error">{recentRunsError}</div>}
        <ul className="recent-runs-list">
          {recentRuns.map((run) => (
            <li key={run.id}>
              <Link to={`/execution/${run.id}`}>{run.test_case_name ?? run.test_case_id}</Link>
              <span className="mono"> {run.id}</span>
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
