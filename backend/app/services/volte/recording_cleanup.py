"""VoLTE 중복 Call-ID 녹취 레코드 자동 정리 (2026-07-30 사용자 요청).

VoLTE 기본 호처리 시험은 매번 같은 pcap을 재생하는데, pcap 안에 SIP
Call-ID가 고정값으로 박혀있어서 같은 Test Case를 반복 실행하면 VCMM의
녹취 DB(MariaDB, VCS 로컬)에서 같은 Call-ID로 중복 오류가 난다 — 지금까지는
매번 사용자가 VCS에 SSH 접속해 mysql 계정으로 아래 두 DELETE를 수동
실행한 뒤에야 재실행할 수 있었다:

    DELETE FROM TBL_CALL_INFO WHERE SIP_CALLID='<call_id>';
    DELETE FROM TBL_RECORD_INFO WHERE SIP_CALLID='<call_id>';

`VolteBasicCallExecutor`가 vctp 재기동 직전에 이 모듈로 같은 정리를
자동 실행한다 — MariaDB 접속 정보(`vcs_settings_store.resolve_mariadb_credentials`)가
설정돼 있고, 이전 실행에서 파싱해둔 이 Test Case의 Call-ID를 찾을 수 있을 때만
동작한다(둘 중 하나라도 없으면 조용히 건너뛴다 — 예: 이 Test Case의 첫 실행이라
아직 알려진 Call-ID가 없는 경우, 또는 이 기능을 쓰지 않는 배포).

정리 자체가 실패해도(DB 접속 불가 등) 시험 실행을 막지 않는다 — 실패하면
경고만 로그로 남기고 계속 진행한다(기존 수동 절차와 최종 결과는 동일하다:
VCMM이 중복으로 거부하면 그 시험만 실패로 판정될 뿐, 인프라 전체가 막히지는
않는다).
"""
from __future__ import annotations

import logging
import shlex

from app.services.ssh_connector import SSHConnector
from app.services.vcs_settings_store import MariaDbCredentials

logger = logging.getLogger(__name__)


def _escape_sql_literal(value: str) -> str:
    """MySQL/MariaDB 문자열 리터럴 이스케이프(백슬래시 -> 작은따옴표 순서로
    처리해야 한다 — 백슬래시를 나중에 이스케이프하면 방금 만든 이스케이프
    시퀀스까지 다시 이스케이프해버린다)."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def build_cleanup_sql(
    call_id: str,
    *,
    call_info_table: str,
    record_info_table: str,
    callid_column: str,
) -> str:
    """사용자가 수동으로 실행하던 두 DELETE문을 그대로 생성한다."""
    escaped = _escape_sql_literal(call_id)
    return (
        f"DELETE FROM {call_info_table} WHERE {callid_column}='{escaped}'; "
        f"DELETE FROM {record_info_table} WHERE {callid_column}='{escaped}';"
    )


def build_cleanup_command(sql: str, *, credentials: MariaDbCredentials) -> str:
    """`mysql -u... -p... db -e "..."` 형태의 원격 셸 커맨드를 만든다.

    셸 인젝션 방지를 위해 사용자명/비밀번호/DB명/SQL 전부 `shlex.quote()`로
    감싼다 — `-u`/`-p`는 mysql CLI 관례대로 값과 공백 없이 붙여 쓴다(예:
    `-p'secret'`는 셸에서 하나의 인자 `-psecret`로 합쳐진다). SQL 리터럴
    안의 작은따옴표는 `build_cleanup_sql`이 이미 이스케이프했으므로, 여기서는
    셸 레이어 인젝션만 막으면 된다.
    """
    return (
        f"mysql -u{shlex.quote(credentials.user)} "
        f"-p{shlex.quote(credentials.password)} "
        f"{shlex.quote(credentials.database)} "
        f"-e {shlex.quote(sql)}"
    )


async def cleanup_stale_recording(
    connector: SSHConnector,
    call_id: str,
    *,
    credentials: MariaDbCredentials,
    call_info_table: str,
    record_info_table: str,
    callid_column: str,
    run_id: str,
) -> None:
    """이전 실행에서 같은 Call-ID로 남아있을 수 있는 녹취 레코드를 지운다.

    실패해도 예외를 올리지 않는다 — 이 정리는 "있으면 좋은" 전처리일 뿐,
    실패했다고 시험 실행 자체를 막을 이유는 없다.
    """
    if not call_id:
        return
    sql = build_cleanup_sql(
        call_id,
        call_info_table=call_info_table,
        record_info_table=record_info_table,
        callid_column=callid_column,
    )
    command = build_cleanup_command(sql, credentials=credentials)
    try:
        result = await connector.run_command(command)
    except Exception:
        logger.warning(
            "VolteExecutor(%s): 녹취 DB 정리 명령 실행 실패(call_id=%s)", run_id, call_id, exc_info=True
        )
        return
    if not result.ok:
        logger.warning(
            "VolteExecutor(%s): 녹취 DB 정리 실패(call_id=%s, exit=%s): %s",
            run_id,
            call_id,
            result.exit_status,
            result.stderr or result.stdout,
        )
    else:
        logger.info("VolteExecutor(%s): 이전 Call-ID(%s) 녹취 레코드 정리 완료", run_id, call_id)
