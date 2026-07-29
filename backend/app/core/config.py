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

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# CLAUDE.md §5: storage/ 는 backend/가 아니라 저장소 루트에 위치한다
# (storage/logs/{test_case_id}/{run_id}/...). uvicorn/alembic이 backend/에서
# 실행되든 repo 루트에서 실행되든 항상 같은 위치를 가리키도록, cwd에 의존하지
# 않고 이 파일의 위치(backend/app/core/config.py) 기준 상대 경로로 계산한다.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_STORAGE_DIR = _REPO_ROOT / "storage"
_DEFAULT_DATABASE_URL = f"sqlite:///{_DEFAULT_STORAGE_DIR / 'db' / 'vcs_test.db'}"


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
    # SQLite로 시작. PostgreSQL 전환 시 DATABASE_URL 환경변수만 교체하면 되도록
    # core/database.py에서 SQLAlchemy 엔진 생성 로직을 URL 기반으로 추상화한다.
    database_url: str = Field(default_factory=lambda: _DEFAULT_DATABASE_URL)

    # --- Storage ---
    storage_dir: str = Field(default_factory=lambda: str(_DEFAULT_STORAGE_DIR))

    # --- VCS SSH 접속 정보 (호스트/계정은 배포 환경마다 다르므로 반드시 .env로만 채운다) ---
    vcs_ssh_host: str | None = None
    vcs_ssh_port: int = 22
    vcs_ssh_username: str | None = None
    vcs_ssh_password: str | None = None
    vcs_ssh_private_key_path: str | None = None
    vcs_ssh_known_hosts: str | None = None

    # --- VoLTE(vctp) 실제 경로/명령 (CLAUDE.md §13 확정: 2026-07-29) ---
    # vctp가 재생(replay)할 pcap 샘플 파일들이 있는 디렉토리. Test Case 등록 폼의
    # select box가 이 디렉토리 목록을 보여준다 (app/services/volte/sample_files.py).
    vctp_sample_dir: str = "/home/vcs/vctp/sample"
    # SAMPLEFILE1 항목을 갖고 있는 vctp 사용자 설정 파일의 경로.
    vctp_config_path: str = "/home/vcs/vctp/config/vctp_user.config"
    vctp_stop_cmd: str = "stopmc -b vctp"
    vctp_start_cmd: str = "startmc -b vctp"
    vcs_vcsm_log_path: str = "/home/vcs/vcsm/logs/vcsm.log"
    vcs_vcmm_log_path: str = "/home/vcs/vcmm/logs/vcmm0.log"
    vcs_vcmc_log_path: str = "/home/vcs/vcmc/logs/vcmc.log"
    # 패킷 릴레이 로그(대부분 노이즈, CLAUDE.md §9)라 우선순위는 낮지만, 대시보드에서
    # 프로세스별 탭으로 보여달라는 요청에 따라 다른 로그와 동일하게 tail 대상에 포함한다.
    vcs_vctp_log_path: str = "/home/vcs/vctp/logs/vctp0.log"

    # --- SIPp 실행 대상 (실행 위치는 TestCase.protocol_params.sipp_exec_mode 또는
    # 아래 기본값으로 결정. 별도 SIPp 전용 호스트를 쓰는 배포는 SIPP_EXEC_MODE=ssh로 설정) ---
    sipp_exec_mode: str = "local"  # "local" | "ssh"
    sipp_ssh_host: str | None = None
    sipp_ssh_port: int = 22
    sipp_ssh_username: str | None = None
    sipp_ssh_password: str | None = None
    sipp_ssh_private_key_path: str | None = None
    # SIPp 원격 호스트에 시나리오/로그를 두는 작업 디렉토리 (실행마다 test_case_id/run_id 하위에 생성).
    sipp_remote_work_dir: str = "/tmp/vcs_test_sipp"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def repo_root_path(self) -> Path:
        """저장소 루트 경로. `TestCase.config_ref`(예: `configs/volte/*.conf`,
        `scenarios/sipp/*.xml`)처럼 저장소 루트 기준 상대 경로로 저장된 값을
        실행기(volte/mcptt executor)가 로컬 절대 경로로 해석할 때 사용한다.
        """
        return _REPO_ROOT

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
