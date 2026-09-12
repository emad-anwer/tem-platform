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
