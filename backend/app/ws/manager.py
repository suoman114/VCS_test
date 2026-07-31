"""Test Run별 WebSocket 채널 구독/브로드캐스트 관리자.

log-collector-agent가 실시간 로그 라인을 수집하는 즉시
`manager.broadcast_to_run(run_id, message)`를 호출하면, 해당 run_id를
구독 중인 모든 WebSocket 클라이언트에 전달된다 (CLAUDE.md §3.3: 저장과
스트리밍을 동시에 수행).

message는 반드시 소규모 JSON(payload)이어야 한다. 대용량 로그를 한 번에
욱여넣지 말 것 (token-guardian-agent 원칙과 동일하게, 클라이언트 쪽 전송도
라인 단위/청크 단위로 스트리밍한다).

다른 에이전트 사용법:
    from app.ws.manager import manager

    # API 라우터의 websocket 엔드포인트에서:
    await manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # 클라이언트 ping 등, 필요 시만
    except WebSocketDisconnect:
        await manager.disconnect(run_id, websocket)

    # log-collector-agent 쪽에서:
    await manager.broadcast_to_run(run_id, {"type": "log", "source": "vcs_log", "line": line})
    await manager.broadcast_to_run(run_id, {"type": "status", "status": "running"})
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, run_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[run_id].add(websocket)
        logger.info("WebSocket connected for run_id=%s (total=%d)", run_id, self.active_connection_count(run_id))

    async def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(run_id)
            if conns is not None:
                conns.discard(websocket)
                if not conns:
                    self._connections.pop(run_id, None)
        logger.info("WebSocket disconnected for run_id=%s", run_id)

    async def broadcast_to_run(self, run_id: str, message: dict[str, Any]) -> None:
        """run_id를 구독 중인 모든 클라이언트에 JSON 메시지를 전송한다.

        전송 실패한(끊긴) 연결은 자동으로 제거한다.
        """
        async with self._lock:
            targets = list(self._connections.get(run_id, ()))

        stale: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - 연결 종료 등 다양한 예외를 일괄 처리
                stale.append(ws)

        if stale:
            async with self._lock:
                conns = self._connections.get(run_id)
                if conns is not None:
                    for ws in stale:
                        conns.discard(ws)

    def active_connection_count(self, run_id: str) -> int:
        return len(self._connections.get(run_id, ()))


manager = ConnectionManager()
