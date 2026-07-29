"""VCS/SIPp 접속 설정 Pydantic 스키마 (CLAUDE.md §13: 호스트/계정을 .env에만
채우던 것을 대시보드에서도 편집 가능하게 함).

`VcsSettingsRead`는 **효과값(effective value)** 을 돌려준다 — DB에 오버라이드가
있으면 그 값, 없으면 `.env`(`Settings`) 기본값. 그래서 대시보드를 처음 열어도
현재 실제로 쓰이는 값이 폼에 그대로 채워진다. 비밀번호는 절대 원문으로
내려주지 않고 `*_password_set`(bool)만 알려준다.

`VcsSettingsUpdate`는 부분 갱신이다 — 요청 바디에 없는 필드는 그대로 두고,
빈 문자열("")이 오면 오버라이드를 해제(.env 값으로 되돌림)한다. 비밀번호는
필드 자체를 보내지 않으면 기존 값을 유지하고, 빈 문자열을 보내면 지운다
(.env 비밀번호로 폴백).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

SippExecModeLiteral = Literal["local", "ssh"]


class VcsSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vcs_ssh_host: str | None
    vcs_ssh_port: int
    vcs_ssh_username: str | None
    vcs_ssh_password_set: bool
    vcs_ssh_private_key_path: str | None
    vcs_ssh_known_hosts: str | None

    sipp_exec_mode: SippExecModeLiteral
    sipp_ssh_host: str | None
    sipp_ssh_port: int
    sipp_ssh_username: str | None
    sipp_ssh_password_set: bool
    sipp_ssh_private_key_path: str | None

    updated_at: datetime | None


class VcsSettingsUpdate(BaseModel):
    """모든 필드가 선택적이다 — 보낸 필드만 갱신한다(`exclude_unset` 기준)."""

    vcs_ssh_host: str | None = None
    vcs_ssh_port: int | None = None
    vcs_ssh_username: str | None = None
    vcs_ssh_password: str | None = None
    vcs_ssh_private_key_path: str | None = None
    vcs_ssh_known_hosts: str | None = None

    sipp_exec_mode: SippExecModeLiteral | None = None
    sipp_ssh_host: str | None = None
    sipp_ssh_port: int | None = None
    sipp_ssh_username: str | None = None
    sipp_ssh_password: str | None = None
    sipp_ssh_private_key_path: str | None = None


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
