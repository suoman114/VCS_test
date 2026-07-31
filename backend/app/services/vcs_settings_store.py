"""대시보드에서 편집한 VCS/SIPp 접속 설정(`VcsSettings`)과 `.env`(`Settings`)를
병합해 실제로 쓸 값을 결정하는 계층.

우선순위: DB 오버라이드(대시보드에서 저장한 값, NULL이 아닌 필드만) >
`Settings`(.env) 기본값. McPTT의 `sipp_exec_mode`는 여기에 더해 Test Case별
`protocol_params["sipp_exec_mode"]`가 한 단계 더 우선한다(호출부에서 처리,
CLAUDE.md §7 시험 유형별 오버라이드와 동일한 패턴).

`resolve_sipp_root_password()`: SIPp 전용 호스트가 root 직접 SSH 로그인을
막아놔서(`PermitRootLogin no`) `sipp_ssh_username`(예: sysadm)으로 먼저
접속한 뒤 `su - root`로 전환해야 하는 환경 대응(2026-07-29). 값이 있으면
호출부가 `SSHConnector.run_command_as_su()`를 쓰고, 없으면 기존처럼
`sipp_ssh_username` 권한으로 직접 실행한다.

`SSHConnector`/`executor` 등 SSH 연결이 필요한 곳은 전부 이 모듈의
`resolve_vcs_target()`/`resolve_sipp_target()`을 통해서만 `SSHTarget`을
얻는다 — `SSHTarget.from_vcs_settings()`를 직접 부르면 DB 오버라이드를
놓친다.

각 함수는 짧게 자체 DB 세션을 열고 닫는다(`VolteBasicCallExecutor._fetch_run`과
동일한 패턴) — 호출부(실행기 등)가 매번 세션을 들고 있지 않아도 되게 하기
위함이다.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.models.vcs_settings import SINGLETON_ID, VcsSettings
from app.services.ssh_connector.client import SSHTarget


@dataclass(frozen=True)
class MariaDbCredentials:
    """VCS 로컬 MariaDB(녹취 DB) 접속 정보 — VoLTE 중복 Call-ID 자동 정리용
    (2026-07-30). `resolve_mariadb_credentials()`가 셋 다 채워져 있을 때만
    반환한다 — 하나라도 비어있으면 기능 자체를 켜지 않는다(기존 동작 유지)."""

    user: str
    password: str
    database: str

# 대시보드 GET/PATCH가 다루는 필드 이름(모델 컬럼 = 스키마 필드 = Settings
# 필드 이름이 대부분 동일해서 하나의 목록으로 병합 로직을 일반화한다).
VCS_FIELDS = (
    "vcs_ssh_host",
    "vcs_ssh_port",
    "vcs_ssh_username",
    "vcs_ssh_private_key_path",
    "vcs_ssh_known_hosts",
)
SIPP_FIELDS = (
    "sipp_exec_mode",
    "sipp_ssh_host",
    "sipp_ssh_port",
    "sipp_ssh_username",
    "sipp_ssh_private_key_path",
)
MARIADB_FIELDS = ("vcs_mariadb_user", "vcs_mariadb_database")
PASSWORD_FIELDS = ("vcs_ssh_password", "sipp_ssh_password", "sipp_ssh_root_password", "vcs_mariadb_password")
ALL_FIELDS = VCS_FIELDS + SIPP_FIELDS + MARIADB_FIELDS + PASSWORD_FIELDS


def get_or_create(db: Session) -> VcsSettings:
    row = db.get(VcsSettings, SINGLETON_ID)
    if row is None:
        row = VcsSettings(id=SINGLETON_ID)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def effective_value(row: VcsSettings, field: str, settings: Settings) -> object:
    """DB 오버라이드(NULL이 아니면)가 있으면 그 값, 없으면 `Settings`(.env) 값."""
    override = getattr(row, field)
    if override is not None:
        return override
    return getattr(settings, field)


def apply_update(row: VcsSettings, patch: dict[str, object]) -> None:
    """부분 업데이트를 적용한다.

    `patch`에 없는 키는 건드리지 않는다(기존 값 유지 — 특히 비밀번호 필드는
    프론트가 사용자가 실제로 입력했을 때만 포함시킨다). 빈 문자열("")은
    "오버라이드 해제 -> .env 값으로 되돌림"을 뜻하므로 NULL로 저장한다.
    """
    for field, value in patch.items():
        if field not in ALL_FIELDS:
            continue
        if value == "":
            value = None
        setattr(row, field, value)


def resolve_vcs_target(settings: Settings | None = None) -> SSHTarget:
    s = settings or get_settings()
    db = SessionLocal()
    try:
        row = get_or_create(db)
        host = effective_value(row, "vcs_ssh_host", s)
        if not host:
            raise ValueError("VCS_SSH_HOST가 설정되지 않았다 (.env 또는 대시보드 설정 확인)")
        return SSHTarget(
            host=host,  # type: ignore[arg-type]
            port=effective_value(row, "vcs_ssh_port", s) or 22,  # type: ignore[arg-type]
            username=effective_value(row, "vcs_ssh_username", s),  # type: ignore[arg-type]
            password=effective_value(row, "vcs_ssh_password", s),  # type: ignore[arg-type]
            private_key_path=effective_value(row, "vcs_ssh_private_key_path", s),  # type: ignore[arg-type]
            known_hosts=effective_value(row, "vcs_ssh_known_hosts", s),  # type: ignore[arg-type]
        )
    finally:
        db.close()


def resolve_sipp_exec_mode(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    db = SessionLocal()
    try:
        row = get_or_create(db)
        return str(effective_value(row, "sipp_exec_mode", s))
    finally:
        db.close()


def resolve_sipp_root_password(settings: Settings | None = None) -> str | None:
    """`su - root` 전환에 쓸 root 비밀번호. 비어있으면(None) 호출부가 su 없이
    `sipp_ssh_username` 권한으로 직접 실행한다(기존 동작, 하위 호환)."""
    s = settings or get_settings()
    db = SessionLocal()
    try:
        row = get_or_create(db)
        value = effective_value(row, "sipp_ssh_root_password", s)
        return str(value) if value else None
    finally:
        db.close()


def resolve_mariadb_credentials(settings: Settings | None = None) -> MariaDbCredentials | None:
    """VCS 녹취 DB(MariaDB) 접속 정보. user/password/database 셋 다 채워져
    있어야 `MariaDbCredentials`를 반환한다 — 하나라도 비어있으면 `None`을
    반환해서 호출부(VolteBasicCallExecutor)가 자동 정리를 건너뛰게 한다."""
    s = settings or get_settings()
    db = SessionLocal()
    try:
        row = get_or_create(db)
        user = effective_value(row, "vcs_mariadb_user", s)
        password = effective_value(row, "vcs_mariadb_password", s)
        database = effective_value(row, "vcs_mariadb_database", s)
        if not user or not password or not database:
            return None
        return MariaDbCredentials(user=str(user), password=str(password), database=str(database))
    finally:
        db.close()


def resolve_sipp_target(settings: Settings | None = None) -> SSHTarget:
    s = settings or get_settings()
    db = SessionLocal()
    try:
        row = get_or_create(db)
        host = effective_value(row, "sipp_ssh_host", s)
        if not host:
            raise ValueError("SIPP_SSH_HOST가 설정되지 않았다 (.env 또는 대시보드 설정 확인)")
        return SSHTarget(
            host=host,  # type: ignore[arg-type]
            port=effective_value(row, "sipp_ssh_port", s) or 22,  # type: ignore[arg-type]
            username=effective_value(row, "sipp_ssh_username", s),  # type: ignore[arg-type]
            password=effective_value(row, "sipp_ssh_password", s),  # type: ignore[arg-type]
            private_key_path=effective_value(row, "sipp_ssh_private_key_path", s),  # type: ignore[arg-type]
            known_hosts=None,
        )
    finally:
        db.close()
