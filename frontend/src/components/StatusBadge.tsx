import type { TestRunStatus } from "../api/types";
import "./StatusBadge.css";

const STATUS_LABEL: Record<TestRunStatus, string> = {
  pending: "대기",
  running: "실행중",
  parsing: "분석중",
  done: "완료",
  failed: "실패",
  error: "오류",
};

const STATUS_CLASS: Record<TestRunStatus, string> = {
  pending: "badge badge-pending",
  running: "badge badge-running",
  parsing: "badge badge-parsing",
  done: "badge badge-done",
  failed: "badge badge-failed",
  error: "badge badge-error",
};

export function StatusBadge({ status }: { status: TestRunStatus | null | undefined }) {
  if (!status) {
    return <span className="badge badge-unknown">알수없음</span>;
  }
  return <span className={STATUS_CLASS[status]}>{STATUS_LABEL[status]}</span>;
}

export function HealthBadge({ ok, label }: { ok: boolean | null; label: string }) {
  const cls = ok === null ? "badge badge-unknown" : ok ? "badge badge-done" : "badge badge-error";
  const text = ok === null ? "확인중" : ok ? "정상" : "오류";
  return (
    <span className="health-badge">
      <span className="health-badge-label">{label}</span>
      <span className={cls}>{text}</span>
    </span>
  );
}
