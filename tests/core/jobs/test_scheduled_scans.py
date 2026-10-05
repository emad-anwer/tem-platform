"""W4-09 (issue #101): sweeper + recurring-scan scheduler tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.context import (
    clear_current_principal,
    get_current_principal,
    set_current_principal,
)
from app.core.auth.principal import Principal, Role
from app.core.jobs.schedule import (
    enqueue_scheduled_scans_once,
    sweep_stale_runs_once,
)
from app.core.jobs.states import ScanRunStatus
from app.core.models import ScanRun
from app.core.repository import ScanRunRepository, TargetRepository


class FakePool:
    """Stand-in for the arq pool: records enqueues, never touches Redis."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, Any, str | None]] = []
        self.fail = fail

    async def enqueue_job(
        self, name: str, payload: Any, _job_id: str | None = None
    ) -> SimpleNamespace:
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.calls.append((name, payload, _job_id))
        return SimpleNamespace(job_id=f"arq-{_job_id}")


def _principal_for(tenant) -> Principal:
    return Principal(user_id="test-setup", tenant_id=tenant.id, role=Role.OWNER)


async def _make_target(db_session, tenant, *, value="lab-nginx", active=True):
    set_current_principal(_principal_for(tenant))
    try:
        return await TargetRepository(db_session).create(
            kind="hostname",
            value=value,
            value_normalized=value,
            is_active=active,
        )
    finally:
        clear_current_principal()


async def _make_running_run(db_session, tenant, target, *, job_id="job-old"):
    set_current_principal(_principal_for(tenant))
    try:
        run = await ScanRunRepository(db_session).create(
            target_id=target.id, max_attempts=3
        )
        claimed = await ScanRunRepository(db_session).claim_for_job(
            run.id, job_id=job_id
        )
        assert claimed is not None
        return run
    finally:
        clear_current_principal()


async def _all_runs(db_session) -> list[ScanRun]:
    return list((await db_session.execute(select(ScanRun))).scalars().all())


@pytest.mark.asyncio
async def test_sweeper_marks_stale_and_leaves_fresh(
    db_session: AsyncSession, two_tenants
) -> None:
    tenant, _ = two_tenants
    target = await _make_target(db_session, tenant)
    stale = await _make_running_run(db_session, tenant, target, job_id="job-old")
    fresh = await _make_running_run(db_session, tenant, target, job_id="job-new")

    stale.started_at = datetime.now(UTC) - timedelta(seconds=700)
    db_session.add(stale)
    await db_session.commit()

    marked = await sweep_stale_runs_once(db_session)

    assert marked == 1
    rows = {run.id: run for run in await _all_runs(db_session)}
    assert rows[stale.id].status == ScanRunStatus.FAILED
    assert rows[stale.id].error_kind == "stale"
    assert rows[fresh.id].status == ScanRunStatus.RUNNING


@pytest.mark.asyncio
async def test_sweeper_is_idempotent(db_session: AsyncSession, two_tenants) -> None:
    tenant, _ = two_tenants
    target = await _make_target(db_session, tenant)
    stale = await _make_running_run(db_session, tenant, target, job_id="job-old")
    stale.started_at = datetime.now(UTC) - timedelta(seconds=700)
    db_session.add(stale)
    await db_session.commit()

    assert await sweep_stale_runs_once(db_session) == 1
    assert await sweep_stale_runs_once(db_session) == 0


@pytest.mark.asyncio
async def test_recurring_enqueues_active_and_skips_inactive(
    db_session: AsyncSession, two_tenants
) -> None:
    tenant, _ = two_tenants
    active = await _make_target(db_session, tenant, value="lab-nginx", active=True)
    await _make_target(db_session, tenant, value="lab-apache", active=False)
    pool = FakePool()

    counts = await enqueue_scheduled_scans_once(
        db_session, pool=pool, limit=50, scheduler_job_id="test-scheduler"
    )

    assert counts == {
        "enqueued": 1,
        "skipped_running": 0,
        "skipped_scope": 0,
        "failed": 0,
    }
    assert len(pool.calls) == 1
    name, payload, job_id = pool.calls[0]
    assert name == "subdomain_discovery_job"
    assert payload.tenant_id == tenant.id
    assert str(payload.run_id) == job_id
    rows = await _all_runs(db_session)
    assert len(rows) == 1
    assert rows[0].target_id == active.id
    assert rows[0].tenant_id == tenant.id
    assert rows[0].status == ScanRunStatus.QUEUED
    # No tenant context leaks out of the loop.
    with pytest.raises(RuntimeError):
        get_current_principal()
    assert "tenant_id" not in structlog.contextvars.get_contextvars()


@pytest.mark.asyncio
async def test_tenant_context_isolated_per_target(
    db_session: AsyncSession, two_tenants
) -> None:
    tenant_a, tenant_b = two_tenants
    target_a = await _make_target(db_session, tenant_a, value="lab-nginx")
    target_b = await _make_target(db_session, tenant_b, value="lab-apache")
    pool = FakePool()

    counts = await enqueue_scheduled_scans_once(
        db_session, pool=pool, limit=50, scheduler_job_id="test-scheduler"
    )

    assert counts["enqueued"] == 2
    payload_tenants = {call[1].tenant_id for call in pool.calls}
    assert payload_tenants == {tenant_a.id, tenant_b.id}
    rows = {run.target_id: run for run in await _all_runs(db_session)}
    assert rows[target_a.id].tenant_id == tenant_a.id
    assert rows[target_b.id].tenant_id == tenant_b.id
    with pytest.raises(RuntimeError):
        get_current_principal()


@pytest.mark.asyncio
async def test_skips_target_with_run_still_running(
    db_session: AsyncSession, two_tenants
) -> None:
    tenant, _ = two_tenants
    target = await _make_target(db_session, tenant)
    await _make_running_run(db_session, tenant, target, job_id="job-busy")
    pool = FakePool()

    counts = await enqueue_scheduled_scans_once(
        db_session, pool=pool, limit=50, scheduler_job_id="test-scheduler"
    )

    assert counts["enqueued"] == 0
    assert counts["skipped_running"] == 1
    assert pool.calls == []
    assert len(await _all_runs(db_session)) == 1


@pytest.mark.asyncio
async def test_scope_refused_target_skips_without_aborting_tick(
    db_session: AsyncSession, two_tenants
) -> None:
    tenant, _ = two_tenants
    await _make_target(db_session, tenant, value="lab-nginx")
    await _make_target(db_session, tenant, value="not a real host !!!")
    pool = FakePool()

    counts = await enqueue_scheduled_scans_once(
        db_session, pool=pool, limit=50, scheduler_job_id="test-scheduler"
    )

    assert counts["enqueued"] == 1
    assert counts["skipped_scope"] == 1


@pytest.mark.asyncio
async def test_enqueue_failure_drops_run_and_continues(
    db_session: AsyncSession, two_tenants
) -> None:
    tenant, _ = two_tenants
    await _make_target(db_session, tenant, value="lab-nginx")
    pool = FakePool(fail=True)

    counts = await enqueue_scheduled_scans_once(
        db_session, pool=pool, limit=50, scheduler_job_id="test-scheduler"
    )

    assert counts["failed"] == 1
    assert counts["enqueued"] == 0
    assert await _all_runs(db_session) == []
