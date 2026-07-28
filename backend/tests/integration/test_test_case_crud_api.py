"""Test Case CRUD API 통합 테스트 (CLAUDE.md §6, §8-1).

`POST/GET/PATCH/DELETE /api/test-cases`의 정상 플로우 + 404/409 케이스를
`httpx.AsyncClient(transport=ASGITransport(app=app))`로 검증한다. DB는
`conftest.isolated_db`가 테스트마다 격리한다.
"""
from __future__ import annotations

import httpx
import pytest


def _payload(name: str = "volte-crud-fixture", **overrides: object) -> dict:
    base: dict = {
        "name": name,
        "category": "volte",
        "test_type": "basic_call",
        "config_ref": "configs/volte/basic_call_default.conf",
        "protocol_params": {"dest_path": "/opt/vcs/conf/vctp.conf"},
        "pass_criteria": {},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_create_get_list_update_delete_flow(client: httpx.AsyncClient) -> None:
    create_resp = await client.post("/api/test-cases", json=_payload())
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    tc_id = created["id"]
    assert created["name"] == "volte-crud-fixture"
    assert created["category"] == "volte"
    assert created["test_type"] == "basic_call"

    get_resp = await client.get(f"/api/test-cases/{tc_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == tc_id

    list_resp = await client.get("/api/test-cases", params={"category": "volte"})
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] >= 1
    assert any(item["id"] == tc_id for item in body["items"])

    name_filter_resp = await client.get("/api/test-cases", params={"name": "crud-fixture"})
    assert name_filter_resp.status_code == 200
    assert any(item["id"] == tc_id for item in name_filter_resp.json()["items"])

    patch_resp = await client.patch(f"/api/test-cases/{tc_id}", json={"description": "updated"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["description"] == "updated"
    # 부분 갱신이므로 건드리지 않은 필드는 유지되어야 한다.
    assert patch_resp.json()["config_ref"] == "configs/volte/basic_call_default.conf"

    delete_resp = await client.delete(f"/api/test-cases/{tc_id}")
    assert delete_resp.status_code == 204

    missing_resp = await client.get(f"/api/test-cases/{tc_id}")
    assert missing_resp.status_code == 404


@pytest.mark.asyncio
async def test_get_missing_test_case_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/test-cases/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_duplicate_name_conflicts_409(client: httpx.AsyncClient) -> None:
    payload = _payload(name="dup-name-case")
    first = await client.post("/api/test-cases", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/test-cases", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_create_duplicate_id_conflicts_409(client: httpx.AsyncClient) -> None:
    first = await client.post("/api/test-cases", json=_payload(name="id-conflict-a"))
    assert first.status_code == 201
    existing_id = first.json()["id"]

    payload2 = _payload(name="id-conflict-b")
    payload2["id"] = existing_id
    second = await client.post("/api/test-cases", json=payload2)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_update_missing_test_case_404(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/api/test-cases/does-not-exist", json={"description": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_missing_test_case_404(client: httpx.AsyncClient) -> None:
    resp = await client.delete("/api/test-cases/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_name_conflict_409(client: httpx.AsyncClient) -> None:
    a = await client.post("/api/test-cases", json=_payload(name="rename-a"))
    b = await client.post("/api/test-cases", json=_payload(name="rename-b"))
    assert a.status_code == 201 and b.status_code == 201
    b_id = b.json()["id"]

    resp = await client.patch(f"/api/test-cases/{b_id}", json={"name": "rename-a"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_invalid_category_422(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/test-cases", params={"category": "bogus"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_invalid_test_type_422(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/test-cases", params={"test_type": "bogus"})
    assert resp.status_code == 422
