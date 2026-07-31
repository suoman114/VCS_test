"""`app.services.volte.recording_cleanup` 단위 테스트 (2026-07-30 추가).

VoLTE 시험이 같은 pcap을 반복 재생하면 pcap에 고정 박힌 SIP Call-ID 때문에
VCMM 녹취 DB(MariaDB)에서 중복 오류가 나던 문제 — 사용자가 확인해준 실제
정리 절차(`DELETE FROM TBL_CALL_INFO/TBL_RECORD_INFO WHERE SIP_CALLID=...`)를
SQL/셸 인젝션 없이 정확히 재현하는지, 그리고 정리 실패가 시험 실행 자체를
막지 않는지를 검증한다.
"""
from __future__ import annotations

import pytest

from app.services.vcs_settings_store import MariaDbCredentials
from app.services.volte.recording_cleanup import (
    build_cleanup_command,
    build_cleanup_sql,
    cleanup_stale_recording,
)

_TABLES = dict(
    call_info_table="TBL_CALL_INFO", record_info_table="TBL_RECORD_INFO", callid_column="SIP_CALLID"
)


def test_build_cleanup_sql_matches_manual_procedure() -> None:
    sql = build_cleanup_sql("abc123@10.0.0.1", **_TABLES)
    assert sql == (
        "DELETE FROM TBL_CALL_INFO WHERE SIP_CALLID='abc123@10.0.0.1'; "
        "DELETE FROM TBL_RECORD_INFO WHERE SIP_CALLID='abc123@10.0.0.1';"
    )


def test_build_cleanup_sql_escapes_single_quote_and_backslash() -> None:
    sql = build_cleanup_sql("call'id\\value", **_TABLES)
    assert "SIP_CALLID='call\\'id\\\\value'" in sql
    # 이스케이프 후에도 원본에 있던 작은따옴표가 SQL 문자열 리터럴을
    # 조기 종료시키지 않아야 한다 — 정확히 2개의 SET 문(세미콜론 2개)만 있어야 함.
    assert sql.count(";") == 2


def test_build_cleanup_command_quotes_credentials_and_sql() -> None:
    creds = MariaDbCredentials(user="root", password="p@ss'; DROP TABLE x; --", database="vcmm")
    command = build_cleanup_command("DELETE FROM t WHERE c='v';", credentials=creds)

    assert command.startswith("mysql -uroot ")
    assert "vcmm" in command
    # 비밀번호에 셸 메타문자(작은따옴표 등)가 섞여 있어도 셸이 하나의
    # 인자로만 해석하도록 안전하게 감싸져 있어야 한다.
    import shlex

    tokens = shlex.split(command)
    assert tokens[0] == "mysql"
    assert tokens[1] == "-uroot"
    assert tokens[2] == "-pp@ss'; DROP TABLE x; --"
    assert tokens[3] == "vcmm"
    assert tokens[4] == "-e"
    assert tokens[5] == "DELETE FROM t WHERE c='v';"


class _FakeResult:
    def __init__(self, ok: bool, exit_status: int = 0, stdout: str = "", stderr: str = "") -> None:
        self._ok = ok
        self.exit_status = exit_status
        self.stdout = stdout
        self.stderr = stderr

    @property
    def ok(self) -> bool:
        return self._ok


class _FakeConnector:
    def __init__(self, result: _FakeResult | Exception) -> None:
        self._result = result
        self.commands: list[str] = []

    async def run_command(self, command: str):
        self.commands.append(command)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


@pytest.mark.asyncio
async def test_cleanup_stale_recording_runs_command_and_reports_success() -> None:
    connector = _FakeConnector(_FakeResult(ok=True))
    creds = MariaDbCredentials(user="root", password="pw", database="vcmm")

    await cleanup_stale_recording(
        connector,  # type: ignore[arg-type]
        "call-1@host",
        credentials=creds,
        run_id="run-1",
        **_TABLES,
    )

    assert len(connector.commands) == 1
    assert "TBL_CALL_INFO" in connector.commands[0]
    assert "call-1@host" in connector.commands[0]


@pytest.mark.asyncio
async def test_cleanup_stale_recording_skips_when_call_id_empty() -> None:
    connector = _FakeConnector(_FakeResult(ok=True))
    creds = MariaDbCredentials(user="root", password="pw", database="vcmm")

    await cleanup_stale_recording(connector, "", credentials=creds, run_id="run-1", **_TABLES)  # type: ignore[arg-type]

    assert connector.commands == []


@pytest.mark.asyncio
async def test_cleanup_stale_recording_does_not_raise_on_command_failure() -> None:
    connector = _FakeConnector(_FakeResult(ok=False, exit_status=1, stderr="ERROR 1045: Access denied"))
    creds = MariaDbCredentials(user="root", password="wrong", database="vcmm")

    # 실패해도 예외를 올리지 않는다 — 시험 실행 자체를 막지 않기 위함.
    await cleanup_stale_recording(connector, "call-1", credentials=creds, run_id="run-1", **_TABLES)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_cleanup_stale_recording_does_not_raise_when_ssh_command_raises() -> None:
    connector = _FakeConnector(ConnectionError("ssh connection lost"))
    creds = MariaDbCredentials(user="root", password="pw", database="vcmm")

    await cleanup_stale_recording(connector, "call-1", credentials=creds, run_id="run-1", **_TABLES)  # type: ignore[arg-type]
