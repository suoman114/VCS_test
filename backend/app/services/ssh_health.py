"""SSH 연결 가능 여부를 실제로 확인하는 공용 헬퍼.

`app/api/health.py`(대시보드 헬스 배지)와 `app/api/settings.py`(설정 화면의
"연결 테스트" 버튼)가 공유한다 — 같은 확인 로직(짧은 타임아웃 + 가벼운
명령 실행)을 두 곳에서 각자 구현하지 않기 위함.
"""
from __future__ import annotations

import asyncio

from app.services.ssh_connector import SSHConnector, SSHTarget

DEFAULT_CONNECT_TIMEOUT_SEC = 3.0


async def check_ssh_reachable(target: SSHTarget, *, timeout: float | None = None) -> tuple[bool, str]:
    """SSH 연결 + 아주 가벼운 명령(`true`) 실행으로 "정말 붙는지" 확인한다.

    연결 자체(TCP handshake 포함)까지 통째로 `timeout`을 씌운다 — 호스트가
    방화벽에 막혀 응답이 아예 없는 경우 OS 기본 TCP 타임아웃(수십 초)까지
    기다리지 않기 위함.

    `timeout`이 함수 정의 시점 기본값이 아니라 호출마다 모듈 상수
    `DEFAULT_CONNECT_TIMEOUT_SEC`를 다시 읽는 이유: 테스트가 이 상수를
    monkeypatch해서 타임아웃 케이스를 빠르게 재현하는데, 파라미터
    기본값(`= DEFAULT_CONNECT_TIMEOUT_SEC`)으로 두면 함수 정의 시점에 한 번만
    평가돼서 이후 monkeypatch가 반영되지 않는다.
    """
    if timeout is None:
        timeout = DEFAULT_CONNECT_TIMEOUT_SEC
    connector = SSHConnector(target)
    try:
        result = await asyncio.wait_for(connector.run_command("true"), timeout=timeout)
        if result.ok:
            return True, f"{target.host}:{target.port} 접속 성공"
        return False, f"명령 실행 실패(exit_status={result.exit_status}): {result.stderr or result.stdout}"
    except TimeoutError:
        return False, f"{target.host}:{target.port} — {timeout:.0f}초 안에 응답 없음(타임아웃)"
    except Exception as exc:  # noqa: BLE001 - 인증 실패/네트워크 등 사유가 다양해 메시지 그대로 전달
        return False, f"{target.host}:{target.port} — {exc}"
    finally:
        await connector.close()
