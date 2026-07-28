"""애플리케이션 설정.

모든 값은 환경변수(.env 포함)에서만 로드한다. SSH 자격증명 등 민감정보는
절대 코드에 하드코딩하지 않는다 (CLAUDE.md 전역 원칙).

다른 에이전트 사용법:
    from app.core.config import get_settings
    settings = get_settings()
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수 기반 전역 설정.

    필드명(대문자화)이 곧 환경변수 이름이다. 예: database_url -> DATABASE_URL
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_name: str = "VCS Test Automation"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173"

    # --- Database ---
    # SQLite로 시작. PostgreSQL 전환 시 이 값만 교체하면 되도록
    # core/database.py에서 SQLAlchemy 엔진 생성 로직을 URL 기반으로 추상화한다.
    database_url: str = "sqlite:///./storage/db/vcs_test.db"

    # --- Storage ---
    storage_dir: str = "storage"

    # --- VCS SSH 접속 정보 (TBD: CLAUDE.md §13 - 인증 방식/네트워크 환경 미확정) ---
    vcs_ssh_host: str | None = None
    vcs_ssh_port: int = 22
    vcs_ssh_username: str | None = None
    vcs_ssh_password: str | None = None
    vcs_ssh_private_key_path: str | None = None
    vcs_ssh_known_hosts: str | None = None

    # --- SIPp 실행 대상 (TBD: CLAUDE.md §13 - 로컬 실행 vs 원격 SSH 실행 미확정) ---
    sipp_exec_mode: str = "local"  # "local" | "ssh"
    sipp_ssh_host: str | None = None
    sipp_ssh_port: int = 22
    sipp_ssh_username: str | None = None
    sipp_ssh_password: str | None = None
    sipp_ssh_private_key_path: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir)

    @property
    def log_storage_path(self) -> Path:
        """원본 로그 저장 위치. CLAUDE.md §3.3: storage/logs/{test_case_id}/{run_id}/..."""
        return self.storage_path / "logs"

    @property
    def db_storage_path(self) -> Path:
        return self.storage_path / "db"


@lru_cache
def get_settings() -> Settings:
    """프로세스 전체에서 재사용되는 Settings 싱글턴."""
    return Settings()
