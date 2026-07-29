"""VCS의 vctp pcap 샘플 디렉토리 목록 조회.

Test Case 등록 폼에서 `sample_file`(protocol_params)을 select box로 고를 수
있도록, `app/api/vcs.py`가 이 함수를 호출해 `GET /api/vcs/volte-sample-files`로
노출한다.
"""
from __future__ import annotations

from app.core.config import Settings, get_settings
from app.services.ssh_connector import SSHConnector, SSHTarget


async def list_volte_sample_files(
    *, settings: Settings | None = None, connector: SSHConnector | None = None
) -> list[str]:
    """`Settings.vctp_sample_dir`(기본 `/home/vcs/vctp/sample`) 안의 파일명 목록.

    `connector`를 주입하면(테스트용) 그 연결을 그대로 쓰고 닫지 않는다.
    주입하지 않으면 이 함수가 직접 연결하고 마지막에 닫는다.
    """
    s = settings or get_settings()
    owns_connector = connector is None
    conn = connector or SSHConnector(SSHTarget.from_vcs_settings(s))
    try:
        result = await conn.run_command(f"ls -1 {s.vctp_sample_dir}")
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout or f"ls {s.vctp_sample_dir} failed")
        return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())
    finally:
        if owns_connector:
            await conn.close()
