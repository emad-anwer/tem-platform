import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs.lifecycle import (
    RetryableJobError,
    TerminalJobError,
    classify_failure,
    execute_scan_run,
    full_jitter_delay,
    mark_stale_runs,
    scrub_failure_message,
)
from app.core.jobs.states import ScanRunStatus, transition_status
from app.core.models import ScanRun
from app.core.repository import ScanRunRepository, TargetRepository


def test_scan_run_transitions_are_centralized() -> None:
    transition_status("queued", ScanRunStatus.RUNNING)
    transition_status("running", ScanRunStatus.FAILED)
    with pytest.raises(ValueError):
        transition_status("failed", ScanRunStatus.RUNNING)


def test_full_jitter_stays_within_exponential_window() -> None:
    assert full_jitter_delay(1, random_value=lambda: 0.5) == 0.5
    assert full_jitter_delay(3, random_value=lambda: 1.0) == 4.0
    assert full_jitter_delay(99, random_value=lambda: 1.0) == 30.0


def test_failure_messages_are_safe() -> None:
    error = RuntimeError("token=secret redis://user:pass@example:6379/0")
    message = scrub_failure_message(error, error_kind="terminal")
    assert message == "terminal: job failed"
    assert "secret" not in message
    assert classify_failure(RetryableJobError()) == "retryable"


@pytest.mark.asyncio
async def test_retry_reuses_one_scan_run(db_session: AsyncSession, two_tenants) -> None:
    tenant, _ = two_tenants
    from app.core.auth.context import set_current_principal
    from app.core.auth.principal import Principal, Role

    set_current_principal(
        Principal(user_id="job", tenant_id=tenant.id, role=Role.OWNER)
    )
    target = await TargetRepository(db_session).create(
        kind="domain", value="example.com", value_normalized="example.com"
    )
    run = await ScanRunRepository(db_session).create(
        target_id=target.id, max_attempts=3
    )
    calls = 0

    async def work(ctx, current_run):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RetryableJobError("upstream unavailable")

    ctx = {"db": db_session, "run_id": run.id, "job_id": "job-1", "job_try": 1}
    with pytest.raises(Retry):
        await execute_scan_run(ctx, work, random_value=lambda: 0.0)

    ctx["job_try"] = 2
    result = await execute_scan_run(ctx, work)
    assert result is not None
    assert result.id == run.id
    assert result.status == ScanRunStatus.SUCCEEDED
    assert result.attempt == 2
    listed_runs, _ = await ScanRunRepository(db_session).list()
    assert len(listed_runs) == 1


@pytest.mark.asyncio
async def test_deadline_marks_run_failed(db_session: AsyncSession, two_tenants) -> None:
    tenant, _ = two_tenants
    from app.core.auth.context import set_current_principal
    from app.core.auth.principal import Principal, Role

    set_current_principal(
        Principal(user_id="job", tenant_id=tenant.id, role=Role.OWNER)
    )
    target = await TargetRepository(db_session).create(
        kind="domain", value="example.com", value_normalized="example.com"
    )
    run = await ScanRunRepository(db_session).create(
        target_id=target.id, max_attempts=1
    )

    async def work(ctx, current_run):
        await asyncio.sleep(0.01)

    result = await execute_scan_run(
        {"db": db_session, "run_id": run.id, "job_id": "job-2", "job_try": 1},
        work,
        max_attempts=1,
        job_timeout=0.001,
    )
    assert result is not None
    assert result.status == ScanRunStatus.FAILED
    assert result.error_kind == "terminal"
    assert result.error_message == "terminal: job deadline exceeded"


@pytest.mark.asyncio
async def test_terminal_error_does_not_retry(
    db_session: AsyncSession, two_tenants
) -> None:
    tenant, _ = two_tenants
    from app.core.auth.context import set_current_principal
    from app.core.auth.principal import Principal, Role

    set_current_principal(
        Principal(user_id="job", tenant_id=tenant.id, role=Role.OWNER)
    )
    target = await TargetRepository(db_session).create(
        kind="domain", value="example.com", value_normalized="example.com"
    )
    run = await ScanRunRepository(db_session).create(
        target_id=target.id, max_attempts=3
    )

    async def work(ctx, current_run):
        raise TerminalJobError("invalid domain")

    result = await execute_scan_run(
        {"db": db_session, "run_id": run.id, "job_id": "job-3", "job_try": 1},
        work,
    )
    assert result is not None
    assert result.status == ScanRunStatus.FAILED
    assert result.attempt == 1


@pytest.mark.asyncio
async def test_stale_runs_are_marked_failed(
    db_session: AsyncSession, two_tenants
) -> None:
    tenant, _ = two_tenants
    from app.core.auth.context import set_current_principal
    from app.core.auth.principal import Principal, Role

    set_current_principal(
        Principal(user_id="job", tenant_id=tenant.id, role=Role.OWNER)
    )
    target = await TargetRepository(db_session).create(
        kind="domain", value="example.com", value_normalized="example.com"
    )
    run = ScanRun(
        tenant_id=tenant.id,
        target_id=target.id,
        status="running",
        max_attempts=3,
        started_at=datetime.now(UTC) - timedelta(seconds=700),
    )
    db_session.add(run)
    await db_session.commit()

    count = await mark_stale_runs(db_session, job_timeout=300, now=datetime.now(UTC))
    assert count == 1
    await db_session.refresh(run)
    assert run.status == ScanRunStatus.FAILED
    assert run.error_kind == "stale"
