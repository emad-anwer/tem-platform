import os
import time
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
import respx
from auth_fixtures import FIXTURE_ISSUER, FIXTURE_PROJECT_ID
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth.dependencies import get_principal
from app.core.auth.principal import Principal, Role
from app.core.auth.token_verifier import JWKSCache, TokenVerifier
from app.core.db import get_db
from app.core.main import create_app
from app.core.models import Base
from app.core.zitadel.client import (
    ZitadelApiError,
    ZitadelOrganization,
    ZitadelUnavailableError,
    get_zitadel_client,
)

pytest_plugins = ["auth_fixtures"]

TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]


class FakeJWKSCache(JWKSCache):
    """A JWKS cache pre-loaded from fixture data — no HTTP, proper __init__."""

    def __init__(
        self,
        fixture_jwks: dict,
        *,
        jwks_uri: str = "https://fake/keys",
        cache_ttl: float = 3600.0,
        refetch_cooldown: float = 30.0,
    ) -> None:
        super().__init__(
            jwks_uri, cache_ttl=cache_ttl, refetch_cooldown=refetch_cooldown
        )
        self._load_fixture(fixture_jwks)

    def _load_fixture(self, fixture_jwks: dict) -> None:
        from jwt import PyJWK

        self._keys = {}
        for key_data in fixture_jwks.get("keys", []):
            kid = key_data.get("kid")
            if kid:
                self._keys[kid] = PyJWK(key_data)
        self._last_fetch = time.monotonic()

    def _fetch_keys(self) -> None:
        """Override to avoid real HTTP calls in most tests."""
        import time

        self._last_fetch = time.monotonic()


@pytest.fixture(scope="session", autouse=True)
def mock_jwks_endpoint(fixture_jwks):
    """Intercept JWKS HTTP calls for the whole test session."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{FIXTURE_ISSUER}/.well-known/jwks.json").mock(
            return_value=Response(200, json=fixture_jwks)
        )

        mock.get(f"{FIXTURE_ISSUER}/oauth/v2/keys").mock(
            return_value=Response(200, json=fixture_jwks)
        )

        # Allow unmocked requests (like Zitadel token fetch in E2E tests) to hit the network
        mock.route().pass_through()

        yield mock


@pytest.fixture
def test_verifier(fixture_jwks) -> TokenVerifier:
    """A TokenVerifier backed by the in-process test JWKS (no HTTP)."""
    cache = FakeJWKSCache(fixture_jwks, jwks_uri=f"{FIXTURE_ISSUER}/oauth/v2/keys")
    return TokenVerifier(
        issuer=FIXTURE_ISSUER,
        audience=FIXTURE_PROJECT_ID,
        jwks_cache=cache,
    )


from sqlalchemy.pool import NullPool


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def create_schema():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    yield


@pytest_asyncio.fixture
async def db_session(create_schema):
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.begin()
            session_maker = async_sessionmaker(
                bind=conn,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with session_maker() as session:
                yield session
            await conn.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def app():
    return create_app()


@pytest_asyncio.fixture
async def two_tenants(db_session: AsyncSession):
    """Two fully provisioned tenants with distinct zitadel_org_ids."""
    from app.core.service import TenantService

    svc = TenantService(db_session)
    tenant_a = await svc.create_tenant(
        name="Tenant Alpha",
        slug="tenant-alpha",
        zitadel_org_id="zitadel-org-alpha-001",
    )
    tenant_b = await svc.create_tenant(
        name="Tenant Beta",
        slug="tenant-beta",
        zitadel_org_id="zitadel-org-beta-002",
    )
    return tenant_a, tenant_b


@pytest_asyncio.fixture
async def client(app, db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_principal] = lambda: Principal(
        user_id="test-platform-admin",
        tenant_id=uuid4(),
        role=Role.PLATFORM_ADMIN,
    )
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()


class FakeZitadelClient:
    """Stands in for ZitadelManagementClient at the get_zitadel_client seam.

    `fail` is a plain mutable attribute (not a constructor-only flag) so a
    test can flip it mid-test — e.g. fail once, then let a retry succeed —
    without needing a second fixture instance.
    """

    def __init__(self) -> None:
        self.fail: str | None = None  # None | "unreachable" | "api_error"
        self.calls: list[str] = []
        self._next_id = 1

    async def create_organization(self, *, name: str) -> ZitadelOrganization:
        if self.fail == "unreachable":
            raise ZitadelUnavailableError("simulated network failure")
        if self.fail == "api_error":
            raise ZitadelApiError("simulated rejection", status_code=400, body="{}")

        self.calls.append(name)

        org = ZitadelOrganization(org_id=f"org-{self._next_id}", name=name)
        self._next_id += 1
        return org


@pytest_asyncio.fixture
async def zitadel(app, client) -> AsyncGenerator[FakeZitadelClient, None]:
    fake = FakeZitadelClient()
    app.dependency_overrides[get_zitadel_client] = lambda: fake
    yield fake
    del app.dependency_overrides[get_zitadel_client]
