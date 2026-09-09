from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Tenant
from app.core.repository import MissingTenantContextError
from tests.jobs.helpers import JobContext, run_job



async def _context_probe(ctx: JobContext, *, label: str = "probe") -> dict[str, Any]:
    """Returns a snapshot of the context it received."""
    return {
        "job_id": ctx.get("job_id"),
        "job_try": ctx.get("job_try"),
        "enqueue_time": ctx.get("enqueue_time"),
        "tenant_id": ctx.get("tenant_id"),
        "has_db": ctx.get("db") is not None,
        "enqueue_time_is_datetime": isinstance(ctx.get("enqueue_time"), datetime),
        "label": label,
    }


async def _tenant_required(ctx: JobContext) -> str:
    """Fails closed when tenant_id is absent."""
    if ctx.get("tenant_id") is None:
        raise MissingTenantContextError(
            "tenant_id absent from job context"
        )
    return f"ok:{ctx['tenant_id']}"


async def _db_write(ctx: JobContext, *, marker: str) -> None:
    """Writes a canary row so tests can verify DB writes are visible."""
    db: AsyncSession = ctx["db"]
    await db.execute(
        text(
            "INSERT INTO tenants (id, name, slug, is_active) "
            "VALUES (gen_random_uuid(), :name, :slug, true)"
        ),
        {"name": f"Canary {marker}", "slug": f"harness-canary-{marker}"},
    )
    await db.flush()


async def test_real_job_executes_in_process(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    """run_job() calls the real function; no worker or Redis involved."""
    result = await run_job(
        _context_probe,
        db=db_session,
        tenant_id=tenant.id,
        try_number=1,
        label="hello",
    )

    assert result["label"] == "hello"
    assert result["has_db"] is True
    assert result["tenant_id"] == tenant.id


async def test_context_contents(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    """The job receives job_id, job_try, enqueue_time, db, and tenant_id."""
    fixed_enqueue = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    fixed_job_id = uuid4()

    result = await run_job(
        _context_probe,
        db=db_session,
        tenant_id=tenant.id,
        try_number=1,
        job_id=fixed_job_id,
        enqueue_time=fixed_enqueue,
    )

    assert result["job_id"] == str(fixed_job_id)
    assert result["job_try"] == 1
    assert result["enqueue_time"] == fixed_enqueue
    assert result["enqueue_time_is_datetime"] is True
    assert result["tenant_id"] == tenant.id
    assert result["has_db"] is True


async def test_retry_simulation(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    """Same job_id, incremented job_try — matches arq's retry model."""
    shared_job_id = uuid4()

    result1 = await run_job(
        _context_probe,
        db=db_session,
        tenant_id=tenant.id,
        try_number=1,
        job_id=shared_job_id,
    )
    result2 = await run_job(
        _context_probe,
        db=db_session,
        tenant_id=tenant.id,
        try_number=2,
        job_id=shared_job_id,
    )

    assert result1["job_id"] == result2["job_id"], "retry must reuse the same job_id"
    assert result1["job_try"] == 1
    assert result2["job_try"] == 2


async def test_missing_tenant_context_fails_closed(
    db_session: AsyncSession,
) -> None:
    """tenant_id=None causes the job to raise MissingTenantContextError."""
    with pytest.raises(MissingTenantContextError):
        await run_job(_tenant_required, db=db_session, tenant_id=None)


async def test_job_db_writes_visible_and_rolled_back(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    """Writes inside a job are visible within the test transaction.

    The savepoint rollback from db_session ensures no data persists
    after the test — the Week 1 isolation guarantee remains intact.
    """
    marker = "isolation-check"

    await run_job(
        _db_write,
        db=db_session,
        tenant_id=tenant.id,
        try_number=1,
        marker=marker,
    )

    result = await db_session.execute(
        text("SELECT slug FROM tenants WHERE slug = :slug"),
        {"slug": f"harness-canary-{marker}"},
    )
    row = result.scalar_one_or_none()
    assert row == f"harness-canary-{marker}", "write must be visible within the test transaction"
