from __future__ import annotations

import functools
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar, runtime_checkable

import structlog

from app.core.auth.context import reset_current_principal, set_current_principal
from app.core.auth.principal import Principal, Role

logger = structlog.get_logger(__name__)

_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])
JOB_REGISTRY: dict[str, Callable[..., Awaitable[Any]]] = {}


@runtime_checkable
class TenantScopedPayload(Protocol):
    """A payload that is scoped to a tenant."""

    tenant_id: uuid.UUID


def system_principal(*, tenant_id: uuid.UUID, job_name: str, job_id: str) -> Principal:
    """Returns a system principal for the given tenant and job."""
    return Principal(
        user_id=f"system:{job_name}:{job_id}",
        role=Role.SYSTEM,
        tenant_id=tenant_id,
    )


def tenant_job(func: _F) -> _F:
    """Decorator to mark a function as a tenant-scoped job.

    The decorated function must accept a payload argument that is an instance of TenantScopedPayload.
    """

    @functools.wraps(func)
    async def wrapper(
        ctx: dict[str, Any], payload: TenantScopedPayload, *args: Any, **kwargs: Any
    ) -> Any:
        tenant_id = getattr(payload, "tenant_id", None)
        if not isinstance(tenant_id, uuid.UUID):
            raise TypeError(
                f"Payload must have a tenant_id attribute of type uuid.UUID, got {type(tenant_id)}"
            )

        job_id = str(ctx.get("job_id", "unknown"))
        principal = system_principal(
            tenant_id=tenant_id, job_name=func.__name__, job_id=job_id
        )

        principal_token = set_current_principal(principal)
        structlog.contextvars.bind_contextvars(
            tenant_id=str(tenant_id), job_id=job_id, job_name=func.__name__
        )

        try:
            return await func(ctx, payload, *args, **kwargs)
        finally:
            reset_current_principal(principal_token)
            structlog.contextvars.clear_contextvars()
            logger.debug(
                "Job finished",
                job_name=func.__name__,
                job_id=job_id,
                tenant_id=str(tenant_id),
            )

    wrapper.__tenant_job__ = True  # type: ignore[attr-defined]
    JOB_REGISTRY[func.__name__] = wrapper  # type: ignore[arg-type]
    return wrapper  # type: ignore[return-value]
