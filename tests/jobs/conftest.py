import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Tenant
from app.core.service import TenantService


@pytest_asyncio.fixture
async def tenant(db_session: AsyncSession) -> Tenant:
    """A single provisioned tenant for job tests.

    Composes the existing db_session fixture so the tenant row participates
    in the savepoint transaction and is rolled back after each test.
    """
    svc = TenantService(db_session)
    return await svc.create_tenant(
        name="Job Test Tenant",
        slug="job-test-tenant",
    )


@pytest_asyncio.fixture
async def other_tenant(db_session: AsyncSession) -> Tenant:
    """A second provisioned tenant for cross-tenant isolation tests."""
    svc = TenantService(db_session)
    return await svc.create_tenant(
        name="Other Job Test Tenant",
        slug="other-job-test-tenant",
    )
