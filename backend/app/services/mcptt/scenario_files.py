"""SIPp 전용 호스트의 McPTT 시나리오 XML 목록 조회.

Test Case 등록 폼에서 `scenario_file`(protocol_params)을 select box로 고를 수
있도록, `app/api/vcs.py`가 이 함수를 호출해 `GET /api/vcs/mcptt-scenario-files`로
노출한다. VoLTE의 `volte/sample_files.py`(pcap 샘플 select box)와 동일한
패턴이다 — 다만 대상 호스트가 VCS가 아니라 SIPp 전용 호스트(`resolve_sipp_target`)
라는 점만 다르다.
"""
from __future__ import annotations

import re

from app.core.config import Settings, get_settings
from app.services.ssh_connector import SSHConnector
from app.services.vcs_settings_store import resolve_sipp_root_password, resolve_sipp_target

# csh/tcsh 로그인 셸의 `ls` alias(색상/페이저 옵션) 우회 — volte/sample_files.py와 동일한 이유.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


async def list_mcptt_scenario_files(
    *, settings: Settings | None = None, connector: SSHConnector | None = None
) -> list[str]:
    """`Settings.mcptt_sim_dir`(기본 `/root/mcptt_sim`) 안의 `*.xml` 파일명 목록.

    `mcptt_sim_dir` 기본값이 `/root` 아래라, root 직접 SSH 로그인이 막힌
    환경(2026-07-29, `sipp_ssh_root_password`)에서는 로그인 계정(예: sysadm)
    권한으로 `ls`하면 대부분 `/root` 디렉토리 자체에 traverse 권한이 없어
    permission denied로 실패한다 — 실제 시뮬레이터 실행(`McpttBasicCallExecutor.
    _run_sipp_remote`)이 이미 이 경우 `run_command_as_su()`로 root 권한으로
    도는 것과 동일하게, 여기서도 `sipp_ssh_root_password`가 설정돼 있으면
    `ls`도 su root로 실행한다(2026-07-30).

    `connector`를 주입하면(테스트용) 그 연결을 그대로 쓰고 닫지 않는다.
    주입하지 않으면 이 함수가 직접 연결하고 마지막에 닫는다.
    """
    s = settings or get_settings()
    owns_connector = connector is None
    conn = connector or SSHConnector(resolve_sipp_target(s))
    try:
        command = f"\\ls -1 {s.mcptt_sim_dir}"
        root_password = resolve_sipp_root_password(s)
        if root_password:
            result = await conn.run_command_as_su(command, root_password)
        else:
            result = await conn.run_command(command)
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout or f"ls {s.mcptt_sim_dir} failed")
        lines = (_ANSI_ESCAPE_RE.sub("", line).strip() for line in result.stdout.splitlines())
        return sorted(line for line in lines if line.endswith(".xml"))
    finally:
        if owns_connector:
            await conn.close()
