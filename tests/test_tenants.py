from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.main import create_app
from app.core.service import get_tenant_service


class FakeTenantService:
    def __init__(self):
        self.tenants = []

    async def create_tenant(self, *, name: str, slug: str, is_active: bool = True):
        for tenant in self.tenants:
            if tenant["slug"] == slug:
                raise ValueError("duplicate slug")
        tenant = {
            "id": str(uuid4()),
            "name": name,
            "slug": slug,
            "is_active": is_active,
            "created_at": "2026-08-29T00:00:00Z",
        }
        self.tenants.append(tenant)
        return tenant

    async def list_tenants(self, *, limit: int, cursor: str | None = None):
        start = int(cursor) if cursor is not None else 0
        items = self.tenants[start : start + limit]
        next_cursor = str(start + limit) if start + limit < len(self.tenants) else None
        return items, next_cursor

    async def get_tenant(self, tenant_id: str):
        for tenant in self.tenants:
            if tenant["id"] == tenant_id:
                return tenant
        return None


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    fake_service = FakeTenantService()
    app.dependency_overrides[get_tenant_service] = lambda: fake_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_tenant_returns_201_and_location_header(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tenants",
        json={"name": "Acme Corp", "slug": "acme-corp"},
    )

    assert response.status_code == 201
    assert response.headers["location"].endswith("/api/v1/tenants/") is False
    payload = response.json()
    assert payload["data"]["type"] == "tenants"
    assert payload["data"]["attributes"]["name"] == "Acme Corp"
    assert payload["data"]["attributes"]["slug"] == "acme-corp"


def test_create_tenant_rejects_invalid_slug(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tenants",
        json={"name": "Bad Slug", "slug": "Bad_Slug"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_list_tenants_returns_cursor_paginated_payload(client: TestClient) -> None:
    client.post("/api/v1/tenants", json={"name": "Acme Corp", "slug": "acme-corp"})
    client.post("/api/v1/tenants", json={"name": "Beta Org", "slug": "beta-org"})

    first_page = client.get("/api/v1/tenants", params={"size": 1})

    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["links"]["next"] is not None
    assert len(first_payload["data"]) == 1
    assert first_payload["data"][0]["type"] == "tenants"

    second_page = client.get(first_payload["links"]["next"])

    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert second_payload["links"]["next"] is None
    assert len(second_payload["data"]) == 1


def test_get_tenant_returns_404_for_unknown_id(client: TestClient) -> None:
    response = client.get("/api/v1/tenants/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_duplicate_slug_returns_409(client: TestClient) -> None:
    client.post("/api/v1/tenants", json={"name": "Acme Corp", "slug": "acme-corp"})

    response = client.post("/api/v1/tenants", json={"name": "Acme Again", "slug": "acme-corp"})

    assert response.status_code == 409
    assert response.json()["title"] == "Conflict"
