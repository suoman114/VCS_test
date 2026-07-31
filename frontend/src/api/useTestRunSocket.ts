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
 *   {"type": "call_flow", "run_id", "mermaid_source", "generated_at"} (execution_common.persist_call_flow/persist_results)
 *
 * **자동 재연결**(2026-07-30 추가): McPTT 성능 시험처럼 실행이 길게 이어지는
 * 경우, 브라우저 탭 백그라운드 전환/네트워크 순단/프록시 idle 타임아웃 등으로
 * WebSocket이 끊기는 일이 실제로 생겼는데, 예전엔 재연결 로직이 전혀 없어서
 * 한 번 끊기면 페이지를 새로고침하기 전까지 실시간 로그가 영원히 멈췄다
 * (사용자 리포트: "로그 출력하는거... 중간에 또 안 나오네"). 지수 백오프로
 * 계속 재연결을 시도한다(최대 15초 간격, 성공하면 백오프 초기화) — 백엔드
 * `SshTailSource`의 `RetryPolicy`(2026-07-30, 기본 무제한 재시도로 변경)와
 * 같은 철학이다.
 */
import { useEffect, useRef, useState } from "react";
import { buildWsUrl } from "./client";
import type { WsMessage } from "./types";

export type SocketStatus = "idle" | "connecting" | "open" | "closed" | "error";

interface UseTestRunSocketResult {
  status: SocketStatus;
  lastMessage: WsMessage | null;
}

const INITIAL_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 15000;

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

    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = INITIAL_RECONNECT_DELAY_MS;

    function scheduleReconnect() {
      if (cancelled) return;
      reconnectTimer = setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
        connect();
      }, reconnectDelay);
    }

    function connect() {
      if (cancelled) return;
      setStatus("connecting");
      try {
        socket = new WebSocket(buildWsUrl(`/ws/test-runs/${runId}`));
      } catch {
        scheduleReconnect();
        return;
      }

      socket.onopen = () => {
        if (cancelled) return;
        setStatus("open");
        reconnectDelay = INITIAL_RECONNECT_DELAY_MS; // 정상 연결되면 백오프를 처음부터 다시 센다.
      };
      socket.onclose = () => {
        if (cancelled) return;
        setStatus("closed");
        scheduleReconnect();
      };
      socket.onerror = () => {
        // WebSocket 스펙상 error 이벤트 뒤에 close 이벤트가 이어진다 — 재연결
        // 예약은 onclose 한 곳에서만 해서 이중 예약을 피한다.
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
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [runId]);

  return { status, lastMessage };
}
