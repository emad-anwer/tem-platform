import asyncio
import dataclasses
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.context import get_current_principal, set_current_principal, reset_current_principal
from app.core.auth.job_context import tenant_job
from app.core.models import Tenant
from app.core.repository import TargetRepository, MissingTenantContextError
from app.core.models import Target
from tests.jobs.helpers import run_job
from app.core.auth.principal import Principal
from app.core.auth.principal import Role


@dataclasses.dataclass(frozen=True, slots=True)
class MockPayload:
    tenant_id: uuid.UUID
    target_id: uuid.UUID


@dataclasses.dataclass(frozen=True, slots=True)
class PayloadMissingTenant:
    target_id: uuid.UUID


@dataclasses.dataclass(frozen=True, slots=True)
class PayloadWrongTenantType:
    tenant_id: str
    target_id: uuid.UUID


@tenant_job
async def job_reads_rows(ctx: dict[str, Any], payload: MockPayload) -> list[Target]:
    db: AsyncSession = ctx["db"]
    repo = TargetRepository(db)
    items, _ = await repo.list()
    return list(items)


async def raw_job_reads_rows(ctx: dict[str, Any], payload: MockPayload) -> list[Target]:
    db: AsyncSession = ctx["db"]
    repo = TargetRepository(db)
    items, _ = await repo.list()
    return list(items)


@tenant_job
async def job_raises_mid_work(ctx: dict[str, Any], payload: MockPayload) -> None:
    db: AsyncSession = ctx["db"]
    repo = TargetRepository(db)
    await repo.list()
    raise ValueError("Something went wrong")


@tenant_job
async def job_suspend(ctx: dict[str, Any], payload: MockPayload) -> list[Target]:
    db: AsyncSession = ctx["db"]
    repo = TargetRepository(db)
    await asyncio.sleep(0.1)
    items, _ = await repo.list()
    return list(items)

@tenant_job
async def job_captures_principal(ctx: dict[str, Any], payload: MockPayload) -> Principal:
    return get_current_principal()


async def test_job_with_context_reads_only_own_tenant_rows(
    db_session: AsyncSession, tenant: Tenant, other_tenant: Tenant
) -> None:
    # Setup data
    target1 = Target(id=uuid.uuid4(), tenant_id=tenant.id, kind="ip", value="1.1.1.1", value_normalized="1.1.1.1")
    target2 = Target(id=uuid.uuid4(), tenant_id=other_tenant.id, kind="ip", value="2.2.2.2", value_normalized="2.2.2.2")
    db_session.add_all([target1, target2])
    await db_session.flush()

    payload = MockPayload(tenant_id=tenant.id, target_id=uuid.uuid4())
    results = await run_job(job_reads_rows, payload, db=db_session, tenant_id=tenant.id)

    assert len(results) == 1
    assert results[0].id == target1.id
    assert results[0].tenant_id == tenant.id


async def test_job_forgets_context_raises(db_session: AsyncSession, tenant: Tenant) -> None:
    target = Target(id=uuid.uuid4(), tenant_id=tenant.id, kind="ip", value="1.1.1.1", value_normalized="1.1.1.1")
    db_session.add(target)
    await db_session.flush()

    payload = MockPayload(tenant_id=tenant.id, target_id=uuid.uuid4())
    # raw_job_reads_rows has no @tenant_job decorator
    with pytest.raises(MissingTenantContextError):
        await run_job(raw_job_reads_rows, payload, db=db_session, tenant_id=None)


async def test_job_raises_leaves_no_context_behind(db_session: AsyncSession, tenant: Tenant) -> None:
    target = Target(id=uuid.uuid4(), tenant_id=tenant.id, kind="ip", value="1.1.1.1", value_normalized="1.1.1.1")
    db_session.add(target)
    await db_session.flush()

    payload = MockPayload(tenant_id=tenant.id, target_id=uuid.uuid4())

    with pytest.raises(MissingTenantContextError):
        await run_job(raw_job_reads_rows, payload, db=db_session, tenant_id=None)

    with pytest.raises(RuntimeError, match="No authenticated principal"):
        get_current_principal()


async def test_two_jobs_interleaved_dont_see_each_other(
    db_session: AsyncSession, tenant: Tenant, other_tenant: Tenant
) -> None:
    target1 = Target(id=uuid.uuid4(), tenant_id=tenant.id, kind="ip", value="1.1.1.1", value_normalized="1.1.1.1")
    target2 = Target(id=uuid.uuid4(), tenant_id=other_tenant.id, kind="ip", value="2.2.2.2", value_normalized="2.2.2.2")
    db_session.add_all([target1, target2])
    await db_session.flush()

    payload1 = MockPayload(tenant_id=tenant.id, target_id=uuid.uuid4())
    payload2 = MockPayload(tenant_id=other_tenant.id, target_id=uuid.uuid4())

    task1 = asyncio.create_task(run_job(job_suspend, payload1, db=db_session, tenant_id=tenant.id))
    task2 = asyncio.create_task(run_job(job_suspend, payload2, db=db_session, tenant_id=other_tenant.id))

    results1, results2 = await asyncio.gather(task1, task2)

    assert len(results1) == 1
    assert results1[0].id == target1.id
    
    assert len(results2) == 1
    assert results2[0].id == target2.id

async def test_job_rejects_missing_tenant_id(db_session: AsyncSession) -> None:
    payload = PayloadMissingTenant(target_id=uuid.uuid4())
    with pytest.raises(TypeError, match="tenant_id"):
        await run_job(job_reads_rows, payload, db=db_session, tenant_id=None)


async def test_job_rejects_wrong_tenant_id_type(db_session: AsyncSession) -> None:
    payload = PayloadWrongTenantType(tenant_id="not-a-uuid", target_id=uuid.uuid4())
    with pytest.raises(TypeError, match="tenant_id"):
        await run_job(job_reads_rows, payload, db=db_session, tenant_id=None)


async def test_outer_principal_restored_after_job(
    db_session: AsyncSession, tenant: Tenant, other_tenant: Tenant
) -> None:
    outer_principal = Principal(user_id="outer-user", role=Role.OWNER, tenant_id=tenant.id)
    token = set_current_principal(outer_principal)
    try:
        payload = MockPayload(tenant_id=other_tenant.id, target_id=uuid.uuid4())
        await run_job(job_reads_rows, payload, db=db_session, tenant_id=other_tenant.id)

        restored = get_current_principal()
        assert restored is outer_principal
        assert restored.tenant_id == tenant.id
    finally:
        reset_current_principal(token)


async def test_job_principal_has_system_role(db_session: AsyncSession, tenant: Tenant) -> None:
    payload = MockPayload(tenant_id=tenant.id, target_id=uuid.uuid4())
    principal = await run_job(job_captures_principal, payload, db=db_session, tenant_id=tenant.id)

    assert principal.role == Role.SYSTEM
    assert principal.tenant_id == tenant.id