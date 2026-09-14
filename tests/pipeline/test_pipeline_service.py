from __future__ import annotations

import pytest

from app.core.auth.context import clear_current_principal, set_current_principal
from app.core.auth.principal import Principal, Role
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.errors import ValidationError as AppValidationError
from app.core.pipeline.service import PipelineService
from app.core.pipeline.validation import TargetKind

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def clean_context():
    clear_current_principal()
    yield
    clear_current_principal()


def _owner(tenant_id):
    return Principal(user_id="owner-user", tenant_id=tenant_id, role=Role.OWNER)


def _viewer(tenant_id):
    return Principal(user_id="viewer-user", tenant_id=tenant_id, role=Role.VIEWER)


async def test_create_target_persists_normalized_value(db_session, two_tenants):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    target = await service.create_target(
        kind=TargetKind.DOMAIN, value="Admin.Example.COM."
    )

    assert target.tenant_id == tenant_a.id
    assert target.kind == "domain"
    assert target.value == "Admin.Example.COM."
    assert target.value_normalized == "admin.example.com"
    assert target.is_active is True


async def test_create_target_viewer_is_forbidden(db_session, two_tenants):
    tenant_a, _ = two_tenants
    principal = _viewer(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    with pytest.raises(ForbiddenError):
        await service.create_target(kind=TargetKind.DOMAIN, value="example.com")


async def test_create_target_invalid_domain_raises_app_validation_error(
    db_session, two_tenants
):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    with pytest.raises(AppValidationError) as exc_info:
        await service.create_target(kind=TargetKind.DOMAIN, value="*.example.com")

    assert exc_info.value.errors[0]["field"] == "value"


async def test_create_target_duplicate_raises_conflict_error(db_session, two_tenants):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    await service.create_target(kind=TargetKind.DOMAIN, value="dupe.example.com")

    with pytest.raises(ConflictError):
        await service.create_target(kind=TargetKind.DOMAIN, value="dupe.example.com")


async def test_list_targets_returns_only_current_tenant_items(db_session, two_tenants):
    tenant_a, tenant_b = two_tenants

    principal_a = _owner(tenant_a.id)
    set_current_principal(principal_a)
    service_a = PipelineService(db_session, principal_a)
    await service_a.create_target(kind=TargetKind.DOMAIN, value="a.example.com")

    principal_b = _owner(tenant_b.id)
    set_current_principal(principal_b)
    service_b = PipelineService(db_session, principal_b)
    await service_b.create_target(kind=TargetKind.DOMAIN, value="b.example.com")

    set_current_principal(principal_a)
    items, next_cursor = await service_a.list_targets(size=20, cursor=None)

    assert {t.value for t in items} == {"a.example.com"}
    assert next_cursor is None


async def test_get_target_or_404_returns_owned_target(db_session, two_tenants):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    created = await service.create_target(
        kind=TargetKind.DOMAIN, value="owned.example.com"
    )

    fetched = await service.get_target_or_404(created.id)
    assert fetched.id == created.id


async def test_get_target_or_404_cross_tenant_is_not_found(db_session, two_tenants):
    tenant_a, tenant_b = two_tenants

    principal_a = _owner(tenant_a.id)
    set_current_principal(principal_a)
    service_a = PipelineService(db_session, principal_a)
    created = await service_a.create_target(
        kind=TargetKind.DOMAIN, value="a-only.example.com"
    )

    principal_b = _owner(tenant_b.id)
    set_current_principal(principal_b)
    service_b = PipelineService(db_session, principal_b)

    with pytest.raises(NotFoundError):
        await service_b.get_target_or_404(created.id)
