"""VCS의 vctp pcap 샘플 디렉토리 목록 조회.

Test Case 등록 폼에서 `sample_file`(protocol_params)을 select box로 고를 수
있도록, `app/api/vcs.py`가 이 함수를 호출해 `GET /api/vcs/volte-sample-files`로
노출한다.
"""
from __future__ import annotations

import re

from app.core.config import Settings, get_settings
from app.services.ssh_connector import SSHConnector, SSHTarget

# 원격 계정의 로그인 셸(csh/tcsh)이 `ls`를 색상/페이저 옵션으로 alias해둔 경우
# (RHEL 계열 기본 .cshrc에 흔함) PTY 할당 후 그 alias가 활성화되면서 ANSI
# 색상 코드가 섞이거나 -1(한 줄에 하나) 옵션이 무시될 수 있다. `\ls`는 csh/bash
# 양쪽에서 공통으로 통하는 "alias 무시하고 실행" 문법이라 이를 우회한다.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


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
        result = await conn.run_command(f"\\ls -1 {s.vctp_sample_dir}")
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout or f"ls {s.vctp_sample_dir} failed")
        lines = (_ANSI_ESCAPE_RE.sub("", line).strip() for line in result.stdout.splitlines())
        return sorted(line for line in lines if line)
    finally:
        if owns_connector:
            await conn.close()
