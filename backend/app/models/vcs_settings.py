"""대시보드에서 편집 가능한 VCS/SIPp 접속 설정 (싱글턴 테이블).

원래 CLAUDE.md 원칙("SSH 자격증명/호스트 정보는 .env로만 관리")은 그대로
유지한다 — `.env`는 여전히 **기본값(초기값)**을 제공한다. 이 테이블은 그
기본값을 대시보드에서 덮어쓸 수 있게 하는 오버레이일 뿐이다. 컬럼이
NULL이면 "오버라이드 없음"을 의미하고, 그 필드는 `Settings`(.env) 값을
그대로 쓴다 (`app/services/vcs_settings_store.py`의 병합 로직 참고).

행은 항상 정확히 1개만 존재한다(`id=SINGLETON_ID` 고정) — 배포 대상 VCS가
여러 대인 경우는 아직 지원하지 않는다(Phase 1 범위 밖, CLAUDE.md에 아직
없는 시나리오).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SINGLETON_ID = "singleton"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VcsSettings(Base):
    __tablename__ = "vcs_settings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=lambda: SINGLETON_ID)

    vcs_ssh_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vcs_ssh_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vcs_ssh_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 평문 저장 — .env 파일에 저장하던 것과 동일한 신뢰 경계(서버 파일시스템/DB
    # 접근 권한이 곧 보호 수단)다. 별도 암호화/시크릿 매니저 연동은 TBD.
    vcs_ssh_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vcs_ssh_private_key_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    vcs_ssh_known_hosts: Mapped[str | None] = mapped_column(String(512), nullable=True)

    sipp_exec_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sipp_ssh_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sipp_ssh_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sipp_ssh_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sipp_ssh_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sipp_ssh_private_key_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<VcsSettings id={self.id} vcs_ssh_host={self.vcs_ssh_host!r}>"
