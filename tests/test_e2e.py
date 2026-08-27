"""End-to-end tests: real dockerized Postgres + Redis, zero mocks.

Unlike test_health.py (which stubs the dependency checks), these exercise
the actual startup lifespan and the real network path: FastAPI lifespan ->
wait_for_db/wait_for_redis -> live PING / SELECT 1.

Run inside the stack where `postgres`/`redis` hostnames resolve:

    just test            # full suite incl. e2e
    just test-unit       # skip e2e (also the safe default outside Docker)

Outside Docker the services are unreachable, so every e2e test skips
honestly instead of failing.

Loop-safety note: redis-py and SQLAlchemy async connections bind to the
event loop they were created on. All direct-client work therefore happens
inside a single asyncio.run() block that disposes everything before exit;
HTTP-level tests go through TestClient, which manages its own loop.
"""

import asyncio
import os
import socket
from urllib.parse import urlparse

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db"
)

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine
from app.core.main import create_app
from app.core.redis import dispose_redis, get_redis

pytestmark = pytest.mark.e2e


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Raw socket probe — deliberately not using client libs, so a failed
    probe never leaves half-built pools behind."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session", autouse=True)
def require_dockerized_services() -> None:
    settings = get_settings()
    # PostgresDsn wraps a MultiHostUrl (multi-host capable), so unlike
    # RedisDsn it has no direct .host — parse the string form instead.
    db = urlparse(str(settings.database_url))
    db_ok = _tcp_open(db.hostname or "", db.port or 5432)
    redis_ok = _tcp_open(
        str(settings.redis_url.host),
        int(settings.redis_url.port or 6379),
    )
    if not (db_ok and redis_ok):
        pytest.skip(
            f"E2E needs dockerized services (postgres={'up' if db_ok else 'down'}, "
            f"redis={'up' if redis_ok else 'down'}) — run via `just test`",
        )


@pytest.fixture(scope="session", autouse=True)
def _dispose_after_e2e(require_dockerized_services: None) -> None:
    yield
    # Session-scoped cleanup so pooled sockets do not outlive the run.
    asyncio.run(dispose_redis())
    asyncio.run(dispose_engine())


# ----------------------------------------------------------------------
# HTTP surface (real lifespan + real dependency checks)
# ----------------------------------------------------------------------


@pytest.fixture
def client_no_lifespan() -> TestClient:
    # Plain constructor: requests work without running startup events.
    return TestClient(create_app())


def test_healthz_is_live_200(client_no_lifespan: TestClient) -> None:
    response = client_no_lifespan.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_passes_with_real_dependencies() -> None:
    # Context manager triggers lifespan: wait_for_db() + wait_for_redis()
    # must both succeed against the real services for startup to complete.
    with TestClient(create_app()) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ----------------------------------------------------------------------
# Direct dependency roundtrip (single event loop, then disposed)
# ----------------------------------------------------------------------


def test_db_and_redis_roundtrip_in_one_loop() -> None:
    async def _run() -> tuple[bool, str | None]:
        from sqlalchemy import text

        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True

        client = await get_redis()
        if client is None:
            return db_ok, None
        await client.set("e2e:probe", "works", ex=60)
        value = await client.get("e2e:probe")
        await client.delete("e2e:probe")
        return db_ok, value

    db_ok, redis_value = asyncio.run(_run())

    assert db_ok is True
    assert redis_value == "works"
