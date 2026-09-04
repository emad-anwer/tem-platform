from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.auth.permissions import (
    PERMISSION_MATRIX,
    Permission,
    require_permission,
)
from app.core.auth.principal import Principal, Role


def principal(role: Role) -> Principal:
    return Principal(user_id="user-1", tenant_id=uuid4(), role=role)


@pytest.mark.asyncio
async def test_viewer_cannot_create_tenants():
    with pytest.raises(HTTPException) as error:
        await require_permission(Permission.TENANT_CREATE)(principal(Role.VIEWER))

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_all_tenant_roles_can_read():
    dependency = require_permission(Permission.TENANT_READ)

    for role in (Role.PLATFORM_ADMIN, Role.OWNER, Role.ANALYST, Role.VIEWER):
        assert await dependency(principal(role)) is not None


def test_permission_matrix_is_the_single_route_policy():
    assert PERMISSION_MATRIX == {
        Permission.TENANT_CREATE: frozenset({Role.PLATFORM_ADMIN}),
        Permission.TENANT_READ: frozenset(
            {Role.PLATFORM_ADMIN, Role.OWNER, Role.ANALYST, Role.VIEWER}
        ),
    }
