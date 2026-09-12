from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, TypedDict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class JobContext(TypedDict, total=False):
    """Shape of the ctx dict arq injects into every job function.

    All external dependencies (DB session, tenant identity) come through
    this dict. Jobs must not reach for them directly — that constraint is
    what makes in-process testing possible and what W3-06/W3-07 must honour.
    """

    job_id: str
    job_try: int
    enqueue_time: datetime
    score: float
    db: AsyncSession
    tenant_id: UUID | None


async def run_job(
    job_fn: Callable[..., Coroutine[Any, Any, Any]],
    *args: Any,
    db: AsyncSession,
    tenant_id: UUID | None = None,
    try_number: int = 1,
    job_id: UUID | None = None,
    enqueue_time: datetime | None = None,
    **kwargs: Any,
) -> Any:
    """Execute a job function in-process against the test DB session.

    No arq worker, no Redis, no independent event loop. The savepoint
    transaction from db_session is preserved — writes are visible within
    the test and rolled back afterwards.

    tenant_id=None tests the fail-closed path; the harness never
    manufactures a tenant.
    """
    resolved_job_id = str(job_id) if job_id is not None else str(uuid.uuid4())
    resolved_enqueue_time = enqueue_time or datetime.now(tz=UTC)

    ctx: JobContext = {
        "job_id": resolved_job_id,
        "job_try": try_number,
        "enqueue_time": resolved_enqueue_time,
        "score": resolved_enqueue_time.timestamp(),
        "db": db,
        "tenant_id": tenant_id,
    }

    return await job_fn(ctx, *args, **kwargs)
