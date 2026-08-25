import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db"
)

import pytest
from fastapi.testclient import TestClient

from app.core import health as health_module
from app.core.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_healthz_is_always_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail() -> bool:
        return False

    monkeypatch.setattr(health_module, "check_db_connection", fail)
    monkeypatch.setattr(health_module, "check_redis_connection", fail)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_is_200_when_db_is_up(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> bool:
        return True

    monkeypatch.setattr(health_module, "check_db_connection", ok)
    monkeypatch.setattr(health_module, "check_redis_connection", ok)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_is_503_when_db_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail() -> bool:
        return False

    async def ok() -> bool:
        return True

    monkeypatch.setattr(health_module, "check_db_connection", fail)
    monkeypatch.setattr(health_module, "check_redis_connection", ok)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_readyz_is_503_when_redis_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail() -> bool:
        return False

    async def ok() -> bool:
        return True

    monkeypatch.setattr(health_module, "check_db_connection", ok)
    monkeypatch.setattr(health_module, "check_redis_connection", fail)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
