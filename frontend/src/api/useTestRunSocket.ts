/**
 * TestRun 실시간 로그/상태 WebSocket 훅.
 *
 * 엔드포인트: `/api/ws/test-runs/{run_id}` (ASSUMED 경로 — log-collector-agent가
 * 메시지 스키마는 확정했으나("log" / "log_source_error"), 정확한 URL 경로는
 * backend-agent 최종 구현에서 바뀔 수 있다. 바뀌면 이 파일의 `buildWsUrl` 호출
 * 부분만 수정하면 된다.)
 *
 * 메시지 스키마(CONFIRMED, log-collector-agent):
 *   {"type": "log", "run_id", "channel": "vcs_log"|"sipp_log", "source", "seq", "line", "ts"}
 *   {"type": "log_source_error", "run_id", "channel", "source", "message", "ts"}
 */
import { useEffect, useRef, useState } from "react";
import { buildWsUrl } from "./client";
import type { WsMessage } from "./types";

export type SocketStatus = "idle" | "connecting" | "open" | "closed" | "error";

interface UseTestRunSocketResult {
  status: SocketStatus;
  lastMessage: WsMessage | null;
}

/**
 * run_id 구독. onMessage 콜백은 매 렌더링마다 새 함수를 넘겨도 안전하도록
 * ref로 감싸서 최신 콜백을 사용한다(재연결 남발 방지).
 */
export function useTestRunSocket(
  runId: string | null,
  onMessage: (msg: WsMessage) => void,
): UseTestRunSocketResult {
  const [status, setStatus] = useState<SocketStatus>("idle");
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!runId) {
      setStatus("idle");
      return;
    }

    let socket: WebSocket | null = null;
    let cancelled = false;

    setStatus("connecting");
    try {
      socket = new WebSocket(buildWsUrl(`/ws/test-runs/${runId}`));
    } catch {
      setStatus("error");
      return;
    }

    socket.onopen = () => {
      if (!cancelled) setStatus("open");
    };
    socket.onclose = () => {
      if (!cancelled) setStatus("closed");
    };
    socket.onerror = () => {
      if (!cancelled) setStatus("error");
    };
    socket.onmessage = (event: MessageEvent<string>) => {
      if (cancelled) return;
      try {
        const parsed = JSON.parse(event.data) as WsMessage;
        setLastMessage(parsed);
        onMessageRef.current(parsed);
      } catch {
        // 파싱 불가능한 메시지는 무시한다 (프로토콜 위반 방어).
      }
    };

    return () => {
      cancelled = true;
      socket?.close();
    };
  }, [runId]);

  return { status, lastMessage };
}
