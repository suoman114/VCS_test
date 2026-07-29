"""VCS SSH 커넥터가 실제로 어떤 raw 결과를 받는지 확인하는 1회성 진단 스크립트.

pcap 샘플 select box가 빈 목록으로 뜨는 문제를 디버깅하기 위한 용도.
가공(ANSI 제거/필터링) 이전의 exit_status/stdout/stderr을 그대로 출력한다.

사용법 (backend/ 디렉토리, venv 활성화 상태):
    python3 scripts/debug_ssh_ls.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncssh  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.ssh_connector import SSHConnector, SSHTarget  # noqa: E402

# 정확히 어떤 채널 요청(pty-req/exec/env 등)을 주고받는지 보기 위한 verbose
# 로그. 비밀번호 등 민감정보는 asyncssh가 로그에 남기지 않는다.
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(message)s")
asyncssh.set_debug_level(3)


async def main() -> None:
    settings = get_settings()
    target = SSHTarget.from_vcs_settings(settings)
    print(f"host={target.host} port={target.port} username={target.username!r}")
    print(f"vctp_sample_dir={settings.vctp_sample_dir!r}")

    connector = SSHConnector(target)
    try:
        command = f"\\ls -1 {settings.vctp_sample_dir}"
        print(f"command={command!r}")
        result = await connector.run_command(command)
        print(f"exit_status={result.exit_status!r}")
        print(f"stdout={result.stdout!r}")
        print(f"stderr={result.stderr!r}")
    finally:
        await connector.close()


if __name__ == "__main__":
    asyncio.run(main())
