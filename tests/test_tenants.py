from httpx import AsyncClient


async def test_create_tenant_succeeds(client: AsyncClient, zitadel) -> None:
    response = await client.post(
        "/api/v1/tenants",
        json={"name": "Acme Corp", "slug": "acme-corp"},
        headers={"Idempotency-Key": "existing-happy-1"},
    )
    assert response.status_code == 201
    assert response.headers["location"].startswith("/api/v1/tenants/")
    payload = response.json()
    assert payload["data"]["type"] == "tenants"
    assert payload["data"]["attributes"]["name"] == "Acme Corp"
    assert payload["data"]["attributes"]["slug"] == "acme-corp"


async def test_duplicate_slug_returns_409(client: AsyncClient, zitadel) -> None:
    await client.post(
        "/api/v1/tenants",
        json={"name": "Acme Corp", "slug": "acme-corp"},
        headers={"Idempotency-Key": "existing-dup-1"},
    )

    response = await client.post(
        "/api/v1/tenants",
        json={"name": "Acme Again", "slug": "acme-corp"},
        headers={
            "Idempotency-Key": "existing-dup-2"
        },  # different key, same slug — a genuine conflict
    )

    assert response.status_code == 409
    assert response.json()["title"] == "Conflict"


async def test_get_tenant_by_id(client: AsyncClient, zitadel) -> None:
    create_response = await client.post(
        "/api/v1/tenants",
        json={"name": "Get Me", "slug": "get-me"},
        headers={"Idempotency-Key": "existing-getbyid-1"},
    )
    assert create_response.status_code == 201
    tenant_id = create_response.json()["data"]["id"]

    response = await client.get(f"/api/v1/tenants/{tenant_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["id"] == tenant_id
    assert payload["data"]["attributes"]["name"] == "Get Me"


async def test_list_returns_created_tenant(client: AsyncClient, zitadel) -> None:
    await client.post(
        "/api/v1/tenants",
        json={"name": "List Me", "slug": "list-me"},
        headers={"Idempotency-Key": "existing-list-1"},
    )

    response = await client.get("/api/v1/tenants")
    assert response.status_code == 200
    payload = response.json()

    slugs = [item["attributes"]["slug"] for item in payload["data"]]
    assert "list-me" in slugs
