import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.auth.context import clear_current_principal, set_current_principal
from app.core.auth.principal import Principal, Role
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.core.errors import ValidationError as AppValidationError
from app.core.jobs.states import ScanRunStatus
from app.core.pipeline.service import PipelineService
from app.core.pipeline.validation import TargetKind
from app.core.repository import FindingRepository


@pytest.fixture(autouse=True)
def clean_context():
    clear_current_principal()
    yield
    clear_current_principal()


def _owner(tenant_id):
    return Principal(user_id="owner-user", tenant_id=tenant_id, role=Role.OWNER)


def _viewer(tenant_id):
    return Principal(user_id="viewer-user", tenant_id=tenant_id, role=Role.VIEWER)


def _patch_arq_pool(monkeypatch, mock_pool):
    """
    Helper that patches get_arq_pool with a proper async function.

    NOTE: `monkeypatch.setattr(..., lambda: mock_pool)` is NOT sufficient here.
    `get_arq_pool` is awaited directly in the service (`pool = await get_arq_pool()`),
    so the patch target must itself be an async callable. A plain lambda returns the
    AsyncMock synchronously, and awaiting an AsyncMock instance directly (rather than
    a call to it) raises `TypeError: object AsyncMock can't be used in 'await' expression`.
    """

    async def _mock_get_arq_pool():
        return mock_pool

    monkeypatch.setattr("app.core.pipeline.service.get_arq_pool", _mock_get_arq_pool)


async def _create_finding(
    findings: FindingRepository,
    *,
    tenant_id,
    target_id,
    title: str,
    severity: str = "LOW",
    last_seen_run_id=None,
):
    """Create a Finding with all required, non-defaulted columns populated.

    The Finding model (see app/core/models.py) requires `kind`, `value`,
    `value_normalized`, `fingerprint` (unique per tenant, CHAR(64)), and
    `first_seen_at`/`last_seen_at` (no column defaults). The scan-run FK is
    named `last_seen_run_id`, not `run_id`/`scan_run_id` -- that's the name
    the repository's `list(run_id=...)` filter actually targets internally.
    `title` is accepted for readability in tests but stored as `value`.
    """
    now = datetime.now(UTC)
    fingerprint = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    return await findings.create(
        tenant_id=tenant_id,
        target_id=target_id,
        last_seen_run_id=last_seen_run_id,
        kind="vulnerability",
        value=title,
        value_normalized=title.lower(),
        fingerprint=fingerprint,
        severity=severity,
        first_seen_at=now,
        last_seen_at=now,
    )


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


async def test_list_targets_invalid_cursor_raises_validation_error(
    db_session, two_tenants
):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    with pytest.raises(AppValidationError) as exc_info:
        await service.list_targets(size=20, cursor="invalid-cursor")

    assert exc_info.value.errors[0]["field"] == "cursor"


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


# ----------------Scan Runs Tests----------------


async def test_start_scan_viewer_is_forbidden(db_session, two_tenants):
    tenant_a, _ = two_tenants
    principal = _viewer(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    with pytest.raises(ForbiddenError):
        await service.start_scan(target_id=uuid.uuid4())


async def test_start_scan_target_not_found_raises_not_found_error(
    db_session, two_tenants
):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    with pytest.raises(NotFoundError):
        await service.start_scan(target_id=uuid.uuid4())


async def test_start_scan_cross_tenant_target_raises_not_found_error(
    db_session, two_tenants
):
    tenant_a, tenant_b = two_tenants

    principal_a = _owner(tenant_a.id)
    set_current_principal(principal_a)
    service_a = PipelineService(db_session, principal_a)
    target = await service_a.create_target(
        kind=TargetKind.DOMAIN, value="target-a.example.com"
    )

    principal_b = _owner(tenant_b.id)
    set_current_principal(principal_b)
    service_b = PipelineService(db_session, principal_b)

    with pytest.raises(NotFoundError):
        await service_b.start_scan(target_id=target.id)


async def test_start_scan_inactive_target_raises_validation_error(
    db_session, two_tenants
):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    target = await service.create_target(
        kind=TargetKind.DOMAIN, value="inactive.example.com"
    )

    target.is_active = False
    await db_session.commit()

    with pytest.raises(AppValidationError) as exc_info:
        await service.start_scan(target_id=target.id)

    assert exc_info.value.errors[0]["field"] == "target_id"


async def test_start_scan_success_enqueues_job_with_tenant_id(
    db_session, two_tenants, monkeypatch
):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    target = await service.create_target(
        kind=TargetKind.DOMAIN, value="scan-me.example.com"
    )

    mock_job = MagicMock()
    mock_job.job_id = "job-abc-123"

    mock_pool = AsyncMock()
    mock_pool.enqueue_job.return_value = mock_job

    _patch_arq_pool(monkeypatch, mock_pool)

    scan_run = await service.start_scan(target_id=target.id)

    assert scan_run.id is not None
    assert scan_run.target_id == target.id
    assert scan_run.status == ScanRunStatus.QUEUED.value
    assert scan_run.arq_job_id == "job-abc-123"

    mock_pool.enqueue_job.assert_called_once()
    call_args = mock_pool.enqueue_job.call_args
    assert call_args[0][0] == "subdomain_discovery_job"

    # Verify SubdomainDiscoveryPayload payload contains required tenant_id
    payload = call_args[0][1]
    assert payload.tenant_id == tenant_a.id
    assert payload.run_id == scan_run.id
    assert call_args[1]["_job_id"] == str(scan_run.id)


async def test_start_scan_job_none_does_not_set_arq_job_id(
    db_session, two_tenants, monkeypatch
):
    """When enqueue_job returns None (e.g. a no-op/backends that don't return a Job),
    the scan run should still succeed but arq_job_id should remain unset."""
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    target = await service.create_target(
        kind=TargetKind.DOMAIN, value="scan-none-job.example.com"
    )

    mock_pool = AsyncMock()
    mock_pool.enqueue_job.return_value = None
    _patch_arq_pool(monkeypatch, mock_pool)

    scan_run = await service.start_scan(target_id=target.id)

    assert scan_run.id is not None
    assert scan_run.status == ScanRunStatus.QUEUED.value
    assert scan_run.arq_job_id is None


async def test_start_scan_enqueue_failure_raises_service_unavailable_error(
    db_session, two_tenants, monkeypatch
):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    target = await service.create_target(
        kind=TargetKind.DOMAIN, value="redis-down.example.com"
    )

    async def mock_get_arq_pool():
        raise RuntimeError("Redis connection error")

    monkeypatch.setattr("app.core.pipeline.service.get_arq_pool", mock_get_arq_pool)

    with pytest.raises(ServiceUnavailableError):
        await service.start_scan(target_id=target.id)

    # Verify that the scan run was cleaned up and not left as a zombie in the DB
    runs, _ = await service._scan_runs.list_by_target(target.id)
    assert len(runs) == 0


async def test_get_scan_run_or_404_returns_owned_scan_run(
    db_session, two_tenants, monkeypatch
):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    target = await service.create_target(
        kind=TargetKind.DOMAIN, value="scan-get.example.com"
    )

    mock_pool = AsyncMock()
    mock_pool.enqueue_job.return_value = None
    _patch_arq_pool(monkeypatch, mock_pool)

    scan_run = await service.start_scan(target_id=target.id)

    fetched = await service.get_scan_run_or_404(scan_run.id)
    assert fetched.id == scan_run.id


async def test_get_scan_run_or_404_not_found_raises_not_found_error(
    db_session, two_tenants
):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    service = PipelineService(db_session, principal)
    with pytest.raises(NotFoundError):
        await service.get_scan_run_or_404(uuid.uuid4())


async def test_get_scan_run_or_404_cross_tenant_raises_not_found_error(
    db_session, two_tenants, monkeypatch
):
    tenant_a, tenant_b = two_tenants

    principal_a = _owner(tenant_a.id)
    set_current_principal(principal_a)
    service_a = PipelineService(db_session, principal_a)
    target = await service_a.create_target(
        kind=TargetKind.DOMAIN, value="a-scan.example.com"
    )

    mock_pool = AsyncMock()
    mock_pool.enqueue_job.return_value = None
    _patch_arq_pool(monkeypatch, mock_pool)

    scan_run = await service_a.start_scan(target_id=target.id)

    principal_b = _owner(tenant_b.id)
    set_current_principal(principal_b)
    service_b = PipelineService(db_session, principal_b)

    with pytest.raises(NotFoundError):
        await service_b.get_scan_run_or_404(scan_run.id)


# ----------------Findings Tests----------------


async def test_list_findings_returns_tenant_scoped_items(
    db_session, two_tenants, monkeypatch
):
    tenant_a, tenant_b = two_tenants

    mock_pool = AsyncMock()
    mock_pool.enqueue_job.return_value = None
    _patch_arq_pool(monkeypatch, mock_pool)

    # Setup Finding for Tenant A
    principal_a = _owner(tenant_a.id)
    set_current_principal(principal_a)
    service_a = PipelineService(db_session, principal_a)
    target_a = await service_a.create_target(
        kind=TargetKind.DOMAIN, value="find-a.example.com"
    )
    scan_run_a = await service_a.start_scan(target_id=target_a.id)

    findings_a = FindingRepository(db_session, tenant_id=tenant_a.id)
    await _create_finding(
        findings_a,
        tenant_id=tenant_a.id,
        target_id=target_a.id,
        title="SQL Injection",
        severity="HIGH",
        last_seen_run_id=scan_run_a.id,
    )

    # Setup Finding for Tenant B
    principal_b = _owner(tenant_b.id)
    set_current_principal(principal_b)
    service_b = PipelineService(db_session, principal_b)
    target_b = await service_b.create_target(
        kind=TargetKind.DOMAIN, value="find-b.example.com"
    )
    scan_run_b = await service_b.start_scan(target_id=target_b.id)

    findings_b = FindingRepository(db_session, tenant_id=tenant_b.id)
    await _create_finding(
        findings_b,
        tenant_id=tenant_b.id,
        target_id=target_b.id,
        title="XSS",
        severity="MEDIUM",
        last_seen_run_id=scan_run_b.id,
    )

    # Query as Tenant A
    set_current_principal(principal_a)
    items, next_cursor = await service_a.list_findings(
        size=10, cursor=None, target_id=None, scan_run_id=None
    )

    assert len(items) == 1
    assert items[0].value == "SQL Injection"
    assert next_cursor is None


async def test_list_findings_filters_by_target_id(db_session, two_tenants, monkeypatch):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    mock_pool = AsyncMock()
    mock_pool.enqueue_job.return_value = None
    _patch_arq_pool(monkeypatch, mock_pool)

    service = PipelineService(db_session, principal)
    target_1 = await service.create_target(
        kind=TargetKind.DOMAIN, value="filter-target-1.example.com"
    )
    scan_run_1 = await service.start_scan(target_id=target_1.id)

    target_2 = await service.create_target(
        kind=TargetKind.DOMAIN, value="filter-target-2.example.com"
    )
    scan_run_2 = await service.start_scan(target_id=target_2.id)

    findings = FindingRepository(db_session, tenant_id=tenant_a.id)
    await _create_finding(
        findings,
        tenant_id=tenant_a.id,
        target_id=target_1.id,
        title="Finding on target 1",
        last_seen_run_id=scan_run_1.id,
    )
    await _create_finding(
        findings,
        tenant_id=tenant_a.id,
        target_id=target_2.id,
        title="Finding on target 2",
        last_seen_run_id=scan_run_2.id,
    )

    items, _ = await service.list_findings(
        size=10, cursor=None, target_id=target_1.id, scan_run_id=None
    )

    assert len(items) == 1
    assert items[0].value == "Finding on target 1"


async def test_list_findings_filters_by_scan_run_id(
    db_session, two_tenants, monkeypatch
):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    mock_pool = AsyncMock()
    mock_pool.enqueue_job.return_value = None
    _patch_arq_pool(monkeypatch, mock_pool)

    service = PipelineService(db_session, principal)
    target = await service.create_target(
        kind=TargetKind.DOMAIN, value="filter-scan-run.example.com"
    )

    matching_scan_run = await service.start_scan(target_id=target.id)
    other_scan_run = await service.start_scan(target_id=target.id)

    matching_scan_run_id = matching_scan_run.id
    other_scan_run_id = other_scan_run.id

    findings = FindingRepository(db_session, tenant_id=tenant_a.id)
    await _create_finding(
        findings,
        tenant_id=tenant_a.id,
        target_id=target.id,
        title="Matching run finding",
        last_seen_run_id=matching_scan_run_id,
    )
    await _create_finding(
        findings,
        tenant_id=tenant_a.id,
        target_id=target.id,
        title="Other run finding",
        last_seen_run_id=other_scan_run_id,
    )

    items, _ = await service.list_findings(
        size=10, cursor=None, target_id=None, scan_run_id=matching_scan_run_id
    )

    assert len(items) == 1
    assert items[0].value == "Matching run finding"
