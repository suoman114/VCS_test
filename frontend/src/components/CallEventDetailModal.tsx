/**
 * Call Flow 메시지 클릭 시 뜨는 "자세히 보기" 팝업 (2026-07-30 요청).
 *
 * 기존 클릭-투-로그(메시지 클릭 → 왼쪽 로그 뷰어가 해당 탭으로 전환되고
 * 그 줄로 스크롤)는 그대로 둔다 — 다만 로그가 길면(특히 성능 시험처럼
 * 이벤트가 수백 건 쌓인 경우) 스크롤해서 하이라이트된 줄을 찾는 게
 * 불편하다는 피드백을 받아, 스크롤 없이 그 자리에서 바로 로그 원문을
 * 볼 수 있는 팝업을 추가로 제공한다.
 *
 * 이 모달은 `LogViewer`가 내부에 들고 있는 CallEvent 캐시에 접근하지
 * 않고 독립적으로 `GET /test-runs/{id}/events`를 조회한다 — LogViewer의
 * 상태를 끌어올리는 리팩터링 없이 두 컴포넌트를 느슨하게 유지하기 위함.
 * `JUMP_FETCH_LIMIT`(LogViewer의 클릭-투-로그 fallback fetch)과 동일한
 * 크기로 한 번에 가져와 seq_no+source로 찾는다 — Test Run당 이벤트 수는
 * CLAUDE.md 기준 수십~수백 건 규모라 이 한도면 충분하다.
 */
import { useEffect, useState } from "react";
import { testRunsApi } from "../api/testRuns";
import type { CallEvent, CallFlowMessage } from "../api/types";
import { labelOfSource } from "../utils/logSourceLabels";
import { formatLogTimestamp } from "../utils/logFormat";
import "./CallEventDetailModal.css";

const FETCH_LIMIT = 1000;

interface CallEventDetailModalProps {
  runId: string;
  message: CallFlowMessage;
  onClose: () => void;
}

export function CallEventDetailModal({ runId, message, onClose }: CallEventDetailModalProps) {
  const [event, setEvent] = useState<CallEvent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setEvent(null);
    testRunsApi
      .getEvents(runId, { limit: FETCH_LIMIT, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        const found = res.items.find((e) => e.source === message.source && e.seq_no === message.seq_no);
        setEvent(found ?? null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "로그 조회 실패");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, message.source, message.seq_no]);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="call-event-modal-backdrop" onClick={onClose}>
      <div className="call-event-modal" onClick={(e) => e.stopPropagation()}>
        <div className="call-event-modal-header">
          <h3>메시지 상세</h3>
          <button type="button" className="call-event-modal-close" onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>

        {loading && <div className="call-event-modal-note">불러오는 중...</div>}
        {error && <div className="call-event-modal-note call-event-modal-error">{error}</div>}

        {!loading && !error && !event && (
          <div className="call-event-modal-note">해당 로그를 찾을 수 없습니다.</div>
        )}

        {event && (
          <>
            <dl className="call-event-modal-meta">
              <dt>소스</dt>
              <dd>{labelOfSource(event.source)}</dd>
              <dt>시각</dt>
              <dd>{formatLogTimestamp(event.ts)}</dd>
              <dt>타입</dt>
              <dd>{event.parsed_type}</dd>
              {event.call_id && (
                <>
                  <dt>Call ID</dt>
                  <dd>{event.call_id}</dd>
                </>
              )}
            </dl>
            <pre className="call-event-modal-raw">{event.raw_line}</pre>
          </>
        )}
      </div>
    </div>
  );
}
