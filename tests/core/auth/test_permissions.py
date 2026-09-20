from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.auth.dependencies import get_principal
from app.core.auth.permissions import (
    PERMISSION_MATRIX,
    Permission,
    require_permission,
    require_role,
)
from app.core.auth.principal import Principal, Role
from app.core.main import create_app
from app.core.routes import router as tenant_router


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


@pytest.mark.asyncio
async def test_require_role_allows_only_declared_roles():
    dependency = require_role(Role.OWNER)

    assert await dependency(principal(Role.OWNER)) is not None

    with pytest.raises(HTTPException) as error:
        await dependency(principal(Role.VIEWER))

    assert error.value.status_code == 403


def test_permission_matrix_is_the_single_route_policy():
    assert PERMISSION_MATRIX == {
        Permission.TENANT_CREATE: frozenset({Role.PLATFORM_ADMIN}),
        Permission.TENANT_READ: frozenset(
            {Role.PLATFORM_ADMIN, Role.OWNER, Role.ANALYST, Role.VIEWER}
        ),
        Permission.TARGET_CREATE: frozenset(
            {Role.PLATFORM_ADMIN, Role.OWNER, Role.ANALYST}
        ),
        Permission.SCAN_START: frozenset(
            {Role.PLATFORM_ADMIN, Role.OWNER, Role.ANALYST}
        ),
    }


def test_existing_tenant_routes_declare_matrix_permissions():
    tenant_routes = {
        route.path: route
        for route in tenant_router.routes
        if isinstance(route, APIRoute)
    }
    route_permissions = {
        route.path: {
            dependency.dependency.__name__ for dependency in route.dependencies
        }
        for route in tenant_routes.values()
    }

    assert route_permissions == {
        "/api/v1/tenants": {"dependency"},
        "/api/v1/tenants/{tenant_id}": {"dependency"},
    }


def test_missing_token_is_401_on_tenant_route():
    response = TestClient(create_app()).get("/api/v1/tenants")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_viewer_is_403_on_tenant_write_route():
    app = create_app()
    app.dependency_overrides[get_principal] = lambda: principal(Role.VIEWER)

    response = TestClient(app).post(
        "/api/v1/tenants",
        json={"name": "Acme Corp", "slug": "acme-corp"},
    )

    assert response.status_code == 403
    app.dependency_overrides.clear()
