import pytest
from httpx import AsyncClient

async def test_create_tenant_succeeds(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/tenants",
        json={"name": "Acme Corp", "slug": "acme-corp"},
    )
    assert response.status_code == 201
    assert response.headers["location"].startswith("/api/v1/tenants/")
    payload = response.json()
    assert payload["name"] == "Acme Corp"
    assert payload["slug"] == "acme-corp"


async def test_duplicate_slug_returns_409(client: AsyncClient) -> None:
    await client.post("/api/v1/tenants", json={"name": "Acme Corp", "slug": "acme-corp"})

    response = await client.post(
        "/api/v1/tenants", json={"name": "Acme Again", "slug": "acme-corp"}
    )

    assert response.status_code == 409
    assert response.json()["title"] == "Conflict"


async def test_get_tenant_by_id(client: AsyncClient) -> None:
    create_response = await client.post(
        "/api/v1/tenants",
        json={"name": "Get Me", "slug": "get-me"},
    )
    assert create_response.status_code == 201
    tenant_id = create_response.json()["id"]

    response = await client.get(f"/api/v1/tenants/{tenant_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == tenant_id
    assert payload["name"] == "Get Me"


async def test_list_returns_created_tenant(client: AsyncClient) -> None:
    await client.post("/api/v1/tenants", json={"name": "List Me", "slug": "list-me"})

    response = await client.get("/api/v1/tenants")
    assert response.status_code == 200
    payload = response.json()

    slugs = [item["slug"] for item in payload["items"]]
    assert "list-me" in slugs
