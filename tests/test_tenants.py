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
    for index in range(3):
        await client.post(
            "/api/v1/tenants",
            json={"name": f"List Me {index}", "slug": f"list-me-{index}"},
            headers={"Idempotency-Key": f"existing-list-{index}"},
        )

    response = await client.get("/api/v1/tenants", params={"size": 1})
    assert response.status_code == 200
    payload = response.json()

    assert len(payload["data"]) == 1
    assert payload["links"]["next"] is not None

    next_response = await client.get(payload["links"]["next"])
    assert next_response.status_code == 200
    next_payload = next_response.json()

    assert len(next_payload["data"]) == 1
    assert next_payload["data"][0]["id"] != payload["data"][0]["id"]
    assert next_payload["links"]["self"].startswith("/api/v1/tenants?size=1&cursor=")
