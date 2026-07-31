"""VCS/SIPp 접속 설정(대시보드 편집) 통합 테스트.

핵심 계약:
- GET은 항상 "효과값"(effective value)을 돌려준다 — DB 오버라이드가 없으면
  `.env`(Settings) 기본값이 그대로 보인다(대시보드를 처음 열어도 현재 실제
  쓰이는 값이 폼에 채워짐).
- PATCH는 부분 갱신이다 — 보낸 필드만 바뀐다. 빈 문자열("")은 오버라이드
  해제(.env로 되돌림)를 뜻한다.
- 비밀번호는 원문으로 절대 안 돌아온다(`*_password_set`만). PATCH 바디에
  비밀번호 필드를 아예 안 보내면 기존 값이 유지된다.
- `resolve_vcs_target`/`resolve_sipp_target`은 DB 오버라이드 > Settings(.env)
  순으로 병합하고, 호스트가 어디에도 없으면 여전히 `ValueError`를 던진다
  (executor/health check가 기대하는 실패 경로 — CLAUDE.md 원칙 유지).
"""
from __future__ import annotations

import httpx
import pytest

import app.api.settings as settings_api_module
from app.core.config import Settings
from app.services.vcs_settings_store import resolve_vcs_target


def _settings_no_overrides(**kwargs: object) -> Settings:
    defaults: dict[str, object] = {"vcs_ssh_host": None, "vcs_ssh_port": 22, "sipp_exec_mode": "local"}
    defaults.update(kwargs)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_returns_env_defaults_when_no_db_override(
    client: httpx.AsyncClient, isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_settings = _settings_no_overrides(vcs_ssh_host="10.0.0.1", vcs_ssh_username="vcs")
    monkeypatch.setattr(settings_api_module, "get_settings", lambda: env_settings)

    resp = await client.get("/api/settings/vcs")

    assert resp.status_code == 200
    body = resp.json()
    assert body["vcs_ssh_host"] == "10.0.0.1"
    assert body["vcs_ssh_username"] == "vcs"
    assert body["vcs_ssh_password_set"] is False
    assert body["sipp_exec_mode"] == "local"


@pytest.mark.asyncio
async def test_patch_overrides_and_get_reflects(
    client: httpx.AsyncClient, isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_settings = _settings_no_overrides(vcs_ssh_host="10.0.0.1")
    monkeypatch.setattr(settings_api_module, "get_settings", lambda: env_settings)

    resp = await client.patch(
        "/api/settings/vcs",
        json={"vcs_ssh_host": "192.168.7.64", "vcs_ssh_port": 2222, "vcs_ssh_password": "s3cr3t"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["vcs_ssh_host"] == "192.168.7.64"
    assert body["vcs_ssh_port"] == 2222
    assert body["vcs_ssh_password_set"] is True

    # 재조회해도(다른 요청) DB에 영속화된 값을 그대로 봐야 한다.
    resp2 = await client.get("/api/settings/vcs")
    body2 = resp2.json()
    assert body2["vcs_ssh_host"] == "192.168.7.64"
    assert body2["vcs_ssh_password_set"] is True


@pytest.mark.asyncio
async def test_patch_omitted_password_field_keeps_existing_value(
    client: httpx.AsyncClient, isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_settings = _settings_no_overrides(vcs_ssh_host="10.0.0.1")
    monkeypatch.setattr(settings_api_module, "get_settings", lambda: env_settings)

    await client.patch("/api/settings/vcs", json={"vcs_ssh_password": "first-secret"})
    resp = await client.patch("/api/settings/vcs", json={"vcs_ssh_username": "vcs2"})

    body = resp.json()
    assert body["vcs_ssh_username"] == "vcs2"
    assert body["vcs_ssh_password_set"] is True  # 안 건드렸으니 그대로 유지


@pytest.mark.asyncio
async def test_patch_empty_string_clears_override_back_to_env(
    client: httpx.AsyncClient, isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_settings = _settings_no_overrides(vcs_ssh_host="10.0.0.1")
    monkeypatch.setattr(settings_api_module, "get_settings", lambda: env_settings)

    await client.patch("/api/settings/vcs", json={"vcs_ssh_host": "192.168.7.64"})
    resp = await client.patch("/api/settings/vcs", json={"vcs_ssh_host": ""})

    assert resp.json()["vcs_ssh_host"] == "10.0.0.1"  # 오버라이드 해제 -> .env 값으로 복귀


@pytest.mark.asyncio
async def test_resolve_vcs_target_prefers_db_override_over_settings(
    isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.vcs_settings_store as store_module

    db = isolated_db()
    try:
        row = store_module.get_or_create(db)
        store_module.apply_update(row, {"vcs_ssh_host": "192.168.7.64", "vcs_ssh_username": "vcs"})
        db.commit()
    finally:
        db.close()

    env_settings = _settings_no_overrides(vcs_ssh_host="10.0.0.1", vcs_ssh_username="env-user")
    target = resolve_vcs_target(env_settings)

    assert target.host == "192.168.7.64"
    assert target.username == "vcs"


@pytest.mark.asyncio
async def test_resolve_vcs_target_raises_when_host_unset_everywhere(isolated_db) -> None:
    env_settings = _settings_no_overrides(vcs_ssh_host=None)

    with pytest.raises(ValueError):
        resolve_vcs_target(env_settings)


@pytest.mark.asyncio
async def test_vcs_test_connection_reports_failure_for_unreachable_host(
    client: httpx.AsyncClient, isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실제 SSH 서버 없이도 검증 가능한 빠른 실패 케이스: 로컬에서 아무도 안
    듣는 포트로 연결을 시도하면 OS가 즉시 ECONNREFUSED를 준다(블랙홀
    호스트처럼 타임아웃까지 기다릴 필요가 없어 테스트가 느려지지 않는다).
    """
    env_settings = _settings_no_overrides(vcs_ssh_host="127.0.0.1", vcs_ssh_port=1)
    monkeypatch.setattr(settings_api_module, "get_settings", lambda: env_settings)

    resp = await client.post("/api/settings/vcs/test-connection")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["message"]


@pytest.mark.asyncio
async def test_sipp_test_connection_local_mode_checks_binary(
    client: httpx.AsyncClient, isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_api_module.shutil, "which", lambda _name: None)

    resp = await client.post("/api/settings/sipp/test-connection")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "sipp" in body["message"]


@pytest.mark.asyncio
async def test_sipp_root_password_is_masked_and_patchable(
    client: httpx.AsyncClient, isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """root 직접 SSH 로그인이 막힌 환경 대응(2026-07-29)으로 추가된
    su root 비밀번호도 다른 비밀번호 필드와 동일한 마스킹/부분갱신 계약을
    따라야 한다."""
    env_settings = _settings_no_overrides(vcs_ssh_host="10.0.0.1")
    monkeypatch.setattr(settings_api_module, "get_settings", lambda: env_settings)

    initial = await client.get("/api/settings/vcs")
    assert initial.json()["sipp_ssh_root_password_set"] is False

    resp = await client.patch("/api/settings/vcs", json={"sipp_ssh_root_password": "r00t-pw"})
    assert resp.json()["sipp_ssh_root_password_set"] is True

    # 다른 필드만 바꿔도(비밀번호 필드 생략) 기존 값이 유지되는지
    resp2 = await client.patch("/api/settings/vcs", json={"sipp_ssh_username": "sysadm"})
    assert resp2.json()["sipp_ssh_root_password_set"] is True


@pytest.mark.asyncio
async def test_mariadb_settings_masked_and_patchable(
    client: httpx.AsyncClient, isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VoLTE 중복 Call-ID 자동 정리(2026-07-30)에 쓰는 VCS 녹취 DB 접속
    정보도 다른 비밀번호 필드와 동일한 마스킹/부분갱신 계약을 따라야 한다."""
    env_settings = _settings_no_overrides(vcs_ssh_host="10.0.0.1")
    monkeypatch.setattr(settings_api_module, "get_settings", lambda: env_settings)

    initial = await client.get("/api/settings/vcs")
    assert initial.json()["vcs_mariadb_user"] is None
    assert initial.json()["vcs_mariadb_password_set"] is False
    assert initial.json()["vcs_mariadb_database"] is None

    resp = await client.patch(
        "/api/settings/vcs",
        json={"vcs_mariadb_user": "root", "vcs_mariadb_password": "pw", "vcs_mariadb_database": "vcmm"},
    )
    body = resp.json()
    assert body["vcs_mariadb_user"] == "root"
    assert body["vcs_mariadb_password_set"] is True
    assert body["vcs_mariadb_database"] == "vcmm"

    # 비밀번호 필드를 생략해도 기존 값이 유지되는지
    resp2 = await client.patch("/api/settings/vcs", json={"vcs_mariadb_user": "root2"})
    assert resp2.json()["vcs_mariadb_password_set"] is True

    # 빈 문자열은 오버라이드 해제(.env 값으로 복귀)
    resp3 = await client.patch("/api/settings/vcs", json={"vcs_mariadb_database": ""})
    assert resp3.json()["vcs_mariadb_database"] is None
