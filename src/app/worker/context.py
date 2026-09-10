"""Structured-logging context helpers for arq job functions.

Every job function should call ``bind_job_context`` at its very first line so
that every structlog call made anywhere in that job's execution carries the
``job_id`` and ``tenant_id`` fields automatically.  This mirrors what
``RequestIDMiddleware`` does for the API's ``request_id``.

The mechanism is ``structlog.contextvars``, which stores bindings in a
``contextvars.Context`` (i.e. per-asyncio-Task, per-thread).  Because arq
runs each job as its own asyncio Task, bindings from one job never bleed into
another — as long as each job calls ``clear_job_context()`` at the end (or
uses the ``job_context`` async context manager, which does it automatically).

Usage inside a job function
---------------------------

    from app.worker.context import job_context

    async def my_job(ctx: dict, *, tenant_id: str) -> None:
        async with job_context(ctx, tenant_id=tenant_id):
            log = structlog.get_logger(__name__)
            await log.ainfo("starting")  # → {job_id: "...", tenant_id: "...", ...}
            ...
"""

import contextlib
from collections.abc import AsyncGenerator

import structlog


def bind_job_context(*, job_id: str, tenant_id: str | None = None) -> None:
    """Bind job_id (and optionally tenant_id) into the structlog context.

    After this call, every ``structlog.get_logger()`` call in the current
    asyncio Task will include these fields automatically.
    """
    fields: dict[str, str] = {"job_id": job_id}
    if tenant_id is not None:
        fields["tenant_id"] = tenant_id
    structlog.contextvars.bind_contextvars(**fields)


def clear_job_context() -> None:
    """Remove all job-specific context vars.

    Call this at the end of every job function (or use the ``job_context``
    async context manager, which calls it automatically).
    """
    structlog.contextvars.unbind_contextvars("job_id", "tenant_id")


@contextlib.asynccontextmanager
async def job_context(
    ctx: dict,
    *,
    tenant_id: str | None = None,
) -> AsyncGenerator[None, None]:
    """Async context manager that binds and clears job context automatically.

    ``ctx`` is the arq context dict passed to every job function; the job ID
    is read from ``ctx["job_id"]``.

    Example::

        async def my_job(ctx: dict, *, tenant_id: str) -> None:
            async with job_context(ctx, tenant_id=tenant_id):
                ...
    """
    job_id: str = ctx.get("job_id", "unknown")
    bind_job_context(job_id=job_id, tenant_id=tenant_id)
    try:
        yield
    finally:
        clear_job_context()
