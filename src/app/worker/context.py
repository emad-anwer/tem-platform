"""Context helpers for structured worker logs."""

import contextlib
from collections.abc import AsyncGenerator

import structlog


def bind_job_context(*, job_id: str, tenant_id: str | None = None) -> None:
    """Bind the current job identifiers to structured logs."""
    fields: dict[str, str] = {"job_id": job_id}
    if tenant_id is not None:
        fields["tenant_id"] = tenant_id
    structlog.contextvars.bind_contextvars(**fields)


def clear_job_context() -> None:
    """Remove the current job identifiers from structured logs."""
    structlog.contextvars.unbind_contextvars("job_id", "tenant_id")


@contextlib.asynccontextmanager
async def job_context(
    ctx: dict,
    *,
    tenant_id: str | None = None,
) -> AsyncGenerator[None, None]:
    """Bind job identifiers for the block and clear them afterwards."""
    job_id: str = ctx.get("job_id", "unknown")
    bind_job_context(job_id=job_id, tenant_id=tenant_id)
    try:
        yield
    finally:
        clear_job_context()
