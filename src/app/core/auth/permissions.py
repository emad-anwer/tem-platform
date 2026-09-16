"""Application authorization policy for route-level permission checks."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.auth.dependencies import get_principal
from app.core.auth.principal import Principal, Role


class Permission(StrEnum):
    TENANT_CREATE = "tenant:create"
    TENANT_READ = "tenant:read"
    TARGET_CREATE = "target:create"
    SCAN_START = "scan:start"


# Zitadel grants roles; this application matrix decides what those roles may do.
PERMISSION_MATRIX: dict[Permission, frozenset[Role]] = {
    Permission.TENANT_CREATE: frozenset({Role.PLATFORM_ADMIN}),
    Permission.TENANT_READ: frozenset(
        {Role.PLATFORM_ADMIN, Role.OWNER, Role.ANALYST, Role.VIEWER}
    ),
    Permission.TARGET_CREATE: frozenset(
        {Role.PLATFORM_ADMIN, Role.OWNER, Role.ANALYST}
    ),
    Permission.SCAN_START: frozenset({Role.PLATFORM_ADMIN, Role.OWNER, Role.ANALYST}),
}


def require_role(*roles: Role) -> Callable:
    """Build a dependency that permits only the supplied normalized roles."""

    async def dependency(
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> Principal:
        if principal.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this operation.",
            )
        return principal

    return dependency


def require_permission(permission: Permission) -> Callable:
    """Build a dependency from the single application permission matrix."""

    allowed_roles = PERMISSION_MATRIX[permission]

    async def dependency(
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> Principal:
        if principal.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permission for this operation.",
            )
        return principal

    return dependency
