from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.job_context import tenant_job
from app.core.models import Tenant
from tests.jobs.helpers import run_job

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class LoggingPayload:
    tenant_id: uuid.UUID


@tenant_job
async def job_emits_log(ctx: dict[str, Any], payload: LoggingPayload) -> None:
    logger.info("job.emits_log.marker")


async def test_job_completion_log_contains_tenant_context(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    payload = LoggingPayload(tenant_id=tenant.id)

    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as captured:
        await run_job(job_emits_log, payload, db=db_session, tenant_id=tenant.id)

    completed = [entry for entry in captured if entry["event"] == "job.completed"]
    assert len(completed) == 1
    assert completed[0]["tenant_id"] == str(tenant.id)
    assert completed[0]["job_name"] == "job_emits_log"


async def test_logging_context_cleaned_up_after_job(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    payload = LoggingPayload(tenant_id=tenant.id)

    await run_job(job_emits_log, payload, db=db_session, tenant_id=tenant.id)

    remaining = structlog.contextvars.get_contextvars()
    assert "tenant_id" not in remaining
    assert "job_id" not in remaining
    assert "job_name" not in remaining


async def test_logging_context_restores_outer_values(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    structlog.contextvars.bind_contextvars(request_id="outer-request")
    try:
        payload = LoggingPayload(tenant_id=tenant.id)
        await run_job(job_emits_log, payload, db=db_session, tenant_id=tenant.id)

        remaining = structlog.contextvars.get_contextvars()
        assert remaining == {"request_id": "outer-request"}
    finally:
        structlog.contextvars.clear_contextvars()
