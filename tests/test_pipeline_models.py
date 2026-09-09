"""Tests for Target, ScanRun, and Finding models and repositories.

Validates:
1. Tenant scoping holds across Target, ScanRun, and Finding repositories.
2. Foreign key cascade deletes (tenant -> target -> scan_run / finding) and SET NULL on last_seen_run_id.
3. Cursor pagination returns every row exactly once across pages without skipping or repeating rows.
4. Unique constraints on (tenant_id, kind, value_normalized) and (tenant_id, fingerprint).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth.context import (
    clear_current_principal,
    set_current_principal,
)
from app.core.auth.principal import Principal, Role
from app.core.models import Base, Finding, ScanRun, Target, Tenant
from app.core.repository import (
    FindingRepository,
    ScanRunRepository,
    TargetRepository,
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable foreign key constraints in SQLite so CASCADE and SET NULL are enforced."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class DummyAsyncSessionWrapper:
    """Synchronous in-memory SQLite wrapper simulating AsyncSession for unit testing."""

    def __init__(self, sync_session: Session) -> None:
        self._session = sync_session

    async def execute(self, statement):
        return self._session.execute(statement)

    def add(self, instance):
        self._session.add(instance)

    async def delete(self, instance):
        self._session.delete(instance)

    async def commit(self):
        self._session.commit()

    async def refresh(self, instance):
        self._session.refresh(instance)

    async def rollback(self):
        self._session.rollback()


@pytest.fixture(autouse=True)
def clean_context():
    clear_current_principal()
    yield
    clear_current_principal()


@pytest.fixture
def sync_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def fake_async_session(sync_db_session):
    return DummyAsyncSessionWrapper(sync_db_session)


@pytest.fixture
def two_tenants_in_db(sync_db_session) -> tuple[Tenant, Tenant]:
    tenant_a = Tenant(
        id=uuid4(),
        name="Tenant Alpha",
        slug="tenant-alpha",
        is_active=True,
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Tenant Beta",
        slug="tenant-beta",
        is_active=True,
    )
    sync_db_session.add(tenant_a)
    sync_db_session.add(tenant_b)
    sync_db_session.commit()
    sync_db_session.refresh(tenant_a)
    sync_db_session.refresh(tenant_b)
    return tenant_a, tenant_b


# ===========================================================================
# 1. Tenant Scoping Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_target_repository_tenant_scoping(fake_async_session, two_tenants_in_db):
    tenant_a, tenant_b = two_tenants_in_db

    # Tenant A creates a target
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    repo_a = TargetRepository(fake_async_session)
    target_a = await repo_a.create(
        kind="domain",
        value="Example.COM.",
        value_normalized="example.com",
    )
    assert target_a.tenant_id == tenant_a.id

    # Tenant B creates a target
    set_current_principal(
        Principal(user_id="user-b", tenant_id=tenant_b.id, role=Role.OWNER)
    )
    repo_b = TargetRepository(fake_async_session)
    target_b = await repo_b.create(
        kind="domain",
        value="Acme.ORG.",
        value_normalized="acme.org",
    )
    assert target_b.tenant_id == tenant_b.id

    # Tenant A context cannot see Tenant B target
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    repo_a_check = TargetRepository(fake_async_session)

    assert await repo_a_check.get_by_id(target_a.id) is not None
    assert await repo_a_check.get_by_id(target_b.id) is None

    items, _ = await repo_a_check.list()
    assert len(items) == 1
    assert items[0].id == target_a.id

    # Cross-tenant update and delete fail
    assert await repo_a_check.update(target_b.id, is_active=False) is None
    assert await repo_a_check.delete(target_b.id) is False


@pytest.mark.asyncio
async def test_scan_run_repository_tenant_scoping(
    fake_async_session, two_tenants_in_db
):
    tenant_a, tenant_b = two_tenants_in_db

    # Setup targets for each tenant
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    target_repo_a = TargetRepository(fake_async_session)
    target_a = await target_repo_a.create(
        kind="domain", value="test-a.com", value_normalized="test-a.com"
    )

    set_current_principal(
        Principal(user_id="user-b", tenant_id=tenant_b.id, role=Role.OWNER)
    )
    target_repo_b = TargetRepository(fake_async_session)
    target_b = await target_repo_b.create(
        kind="domain", value="test-b.com", value_normalized="test-b.com"
    )

    # Create scan runs
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    run_repo_a = ScanRunRepository(fake_async_session)
    run_a = await run_repo_a.create(target_id=target_a.id, max_attempts=3)
    assert run_a.tenant_id == tenant_a.id

    set_current_principal(
        Principal(user_id="user-b", tenant_id=tenant_b.id, role=Role.OWNER)
    )
    run_repo_b = ScanRunRepository(fake_async_session)
    run_b = await run_repo_b.create(target_id=target_b.id, max_attempts=3)
    assert run_b.tenant_id == tenant_b.id

    # Scoping check: Tenant A cannot see Tenant B run
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    run_repo_a_check = ScanRunRepository(fake_async_session)
    assert await run_repo_a_check.get_by_id(run_a.id) is not None
    assert await run_repo_a_check.get_by_id(run_b.id) is None

    runs, _ = await run_repo_a_check.list()
    assert len(runs) == 1
    assert runs[0].id == run_a.id

    # list_by_target check
    runs_by_target_a, _ = await run_repo_a_check.list_by_target(target_a.id)
    assert len(runs_by_target_a) == 1
    assert runs_by_target_a[0].id == run_a.id

    # Trying to list target_b from tenant A returns empty
    runs_by_target_b, _ = await run_repo_a_check.list_by_target(target_b.id)
    assert len(runs_by_target_b) == 0


@pytest.mark.asyncio
async def test_finding_repository_tenant_scoping(fake_async_session, two_tenants_in_db):
    tenant_a, tenant_b = two_tenants_in_db
    now = datetime.now(UTC)

    # Tenant A target & run
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    target_a = await TargetRepository(fake_async_session).create(
        kind="domain", value="test-a.com", value_normalized="test-a.com"
    )
    run_a = await ScanRunRepository(fake_async_session).create(
        target_id=target_a.id, max_attempts=3
    )
    finding_repo_a = FindingRepository(fake_async_session)
    finding_a = await finding_repo_a.create(
        target_id=target_a.id,
        last_seen_run_id=run_a.id,
        kind="subdomain",
        value="admin.test-a.com",
        value_normalized="admin.test-a.com",
        fingerprint="fp-a-1234567890",
        severity="low",
        first_seen_at=now,
        last_seen_at=now,
        details={"ip": "1.2.3.4"},
    )
    assert finding_a.tenant_id == tenant_a.id

    # Tenant B target & run & finding
    set_current_principal(
        Principal(user_id="user-b", tenant_id=tenant_b.id, role=Role.OWNER)
    )
    target_b = await TargetRepository(fake_async_session).create(
        kind="domain", value="test-b.com", value_normalized="test-b.com"
    )
    run_b = await ScanRunRepository(fake_async_session).create(
        target_id=target_b.id, max_attempts=3
    )
    finding_repo_b = FindingRepository(fake_async_session)
    finding_b = await finding_repo_b.create(
        target_id=target_b.id,
        last_seen_run_id=run_b.id,
        kind="subdomain",
        value="admin.test-b.com",
        value_normalized="admin.test-b.com",
        fingerprint="fp-b-1234567890",
        severity="high",
        first_seen_at=now,
        last_seen_at=now,
        details={"ip": "5.6.7.8"},
    )

    # Scoping check: Tenant A cannot see Tenant B finding
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    check_repo_a = FindingRepository(fake_async_session)
    assert await check_repo_a.get_by_id(finding_a.id) is not None
    assert await check_repo_a.get_by_id(finding_b.id) is None

    findings, _ = await check_repo_a.list()
    assert len(findings) == 1
    assert findings[0].id == finding_a.id

    # list_by_target
    findings_by_target_a, _ = await check_repo_a.list_by_target(target_a.id)
    assert len(findings_by_target_a) == 1
    assert findings_by_target_a[0].id == finding_a.id

    findings_by_target_b, _ = await check_repo_a.list_by_target(target_b.id)
    assert len(findings_by_target_b) == 0

    # list_by_run
    findings_by_run_a, _ = await check_repo_a.list_by_run(run_a.id)
    assert len(findings_by_run_a) == 1
    assert findings_by_run_a[0].id == finding_a.id

    findings_by_run_b, _ = await check_repo_a.list_by_run(run_b.id)
    assert len(findings_by_run_b) == 0


# ===========================================================================
# 2. Foreign Key Cascade & SET NULL Tests
# ===========================================================================


def test_tenant_deletion_cascades_to_targets_runs_findings(
    sync_db_session, two_tenants_in_db
):
    tenant_a, _ = two_tenants_in_db
    now = datetime.now(UTC)

    target = Target(
        id=uuid4(),
        tenant_id=tenant_a.id,
        kind="domain",
        value="example.com",
        value_normalized="example.com",
    )
    sync_db_session.add(target)
    sync_db_session.flush()

    run = ScanRun(
        id=uuid4(),
        tenant_id=tenant_a.id,
        target_id=target.id,
        max_attempts=3,
    )
    sync_db_session.add(run)
    sync_db_session.flush()

    finding = Finding(
        id=uuid4(),
        tenant_id=tenant_a.id,
        target_id=target.id,
        last_seen_run_id=run.id,
        kind="subdomain",
        value="admin.example.com",
        value_normalized="admin.example.com",
        fingerprint="fp-cascade-1",
        severity="low",
        first_seen_at=now,
        last_seen_at=now,
    )
    sync_db_session.add(finding)
    sync_db_session.commit()

    # Delete the tenant
    sync_db_session.delete(tenant_a)
    sync_db_session.commit()

    # Verify everything cascaded
    assert (
        sync_db_session.execute(
            select(Target).where(Target.id == target.id)
        ).scalar_one_or_none()
        is None
    )
    assert (
        sync_db_session.execute(
            select(ScanRun).where(ScanRun.id == run.id)
        ).scalar_one_or_none()
        is None
    )
    assert (
        sync_db_session.execute(
            select(Finding).where(Finding.id == finding.id)
        ).scalar_one_or_none()
        is None
    )


def test_target_deletion_cascades_to_runs_and_findings(
    sync_db_session, two_tenants_in_db
):
    tenant_a, _ = two_tenants_in_db
    now = datetime.now(UTC)

    target = Target(
        id=uuid4(),
        tenant_id=tenant_a.id,
        kind="domain",
        value="example.com",
        value_normalized="example.com",
    )
    sync_db_session.add(target)
    sync_db_session.flush()

    run = ScanRun(
        id=uuid4(),
        tenant_id=tenant_a.id,
        target_id=target.id,
        max_attempts=3,
    )
    sync_db_session.add(run)
    sync_db_session.flush()

    finding = Finding(
        id=uuid4(),
        tenant_id=tenant_a.id,
        target_id=target.id,
        last_seen_run_id=run.id,
        kind="subdomain",
        value="admin.example.com",
        value_normalized="admin.example.com",
        fingerprint="fp-cascade-2",
        severity="low",
        first_seen_at=now,
        last_seen_at=now,
    )
    sync_db_session.add(finding)
    sync_db_session.commit()

    # Delete target
    sync_db_session.delete(target)
    sync_db_session.commit()

    assert (
        sync_db_session.execute(
            select(ScanRun).where(ScanRun.id == run.id)
        ).scalar_one_or_none()
        is None
    )
    assert (
        sync_db_session.execute(
            select(Finding).where(Finding.id == finding.id)
        ).scalar_one_or_none()
        is None
    )


def test_scan_run_deletion_sets_null_on_findings(sync_db_session, two_tenants_in_db):
    tenant_a, _ = two_tenants_in_db
    now = datetime.now(UTC)

    target = Target(
        id=uuid4(),
        tenant_id=tenant_a.id,
        kind="domain",
        value="example.com",
        value_normalized="example.com",
    )
    sync_db_session.add(target)
    sync_db_session.flush()

    run = ScanRun(
        id=uuid4(),
        tenant_id=tenant_a.id,
        target_id=target.id,
        max_attempts=3,
    )
    sync_db_session.add(run)
    sync_db_session.flush()

    finding = Finding(
        id=uuid4(),
        tenant_id=tenant_a.id,
        target_id=target.id,
        last_seen_run_id=run.id,
        kind="subdomain",
        value="admin.example.com",
        value_normalized="admin.example.com",
        fingerprint="fp-setnull-1",
        severity="low",
        first_seen_at=now,
        last_seen_at=now,
    )
    sync_db_session.add(finding)
    sync_db_session.commit()

    # Delete scan run
    sync_db_session.delete(run)
    sync_db_session.commit()

    # Finding must NOT be deleted, but last_seen_run_id must be NULL
    refreshed_finding = sync_db_session.execute(
        select(Finding).where(Finding.id == finding.id)
    ).scalar_one_or_none()
    assert refreshed_finding is not None
    assert refreshed_finding.last_seen_run_id is None


# ===========================================================================
# 3. Cursor Pagination Tests (No Rows Skipped or Repeated)
# ===========================================================================


@pytest.mark.asyncio
async def test_target_cursor_pagination_exact_coverage(
    fake_async_session, two_tenants_in_db
):
    tenant_a, _ = two_tenants_in_db
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    repo = TargetRepository(fake_async_session)

    # Create 7 targets
    created_ids: set[UUID] = set()
    for i in range(1, 8):
        t = await repo.create(
            kind="domain",
            value=f"sub{i:02d}.example.com",
            value_normalized=f"sub{i:02d}.example.com",
        )
        created_ids.add(t.id)

    # Page through with limit=2
    seen_ids: list[UUID] = []
    cursor: str | None = None
    page_count = 0

    while True:
        items, cursor = await repo.list(limit=2, cursor=cursor)
        page_count += 1
        for item in items:
            seen_ids.append(item.id)
        if cursor is None:
            break

    # 7 items with limit 2 => pages of 2, 2, 2, 1 (4 pages)
    assert page_count == 4
    assert len(seen_ids) == 7
    # Every row returned exactly once
    assert set(seen_ids) == created_ids
    assert len(set(seen_ids)) == len(seen_ids)


@pytest.mark.asyncio
async def test_scan_run_cursor_pagination_exact_coverage(
    fake_async_session, two_tenants_in_db
):
    tenant_a, _ = two_tenants_in_db
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    target = await TargetRepository(fake_async_session).create(
        kind="domain", value="example.com", value_normalized="example.com"
    )
    repo = ScanRunRepository(fake_async_session)

    created_ids: set[UUID] = set()
    for _ in range(5):
        r = await repo.create(target_id=target.id, max_attempts=3)
        created_ids.add(r.id)

    seen_ids: list[UUID] = []
    cursor: str | None = None

    while True:
        items, cursor = await repo.list_by_target(target.id, limit=2, cursor=cursor)
        for item in items:
            seen_ids.append(item.id)
        if cursor is None:
            break

    assert len(seen_ids) == 5
    assert set(seen_ids) == created_ids
    assert len(set(seen_ids)) == len(seen_ids)


@pytest.mark.asyncio
async def test_finding_cursor_pagination_exact_coverage(
    fake_async_session, two_tenants_in_db
):
    tenant_a, _ = two_tenants_in_db
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    target = await TargetRepository(fake_async_session).create(
        kind="domain", value="example.com", value_normalized="example.com"
    )
    run = await ScanRunRepository(fake_async_session).create(
        target_id=target.id, max_attempts=3
    )
    repo = FindingRepository(fake_async_session)
    now = datetime.now(UTC)

    created_ids: set[UUID] = set()
    for i in range(6):
        f = await repo.create(
            target_id=target.id,
            last_seen_run_id=run.id,
            kind="subdomain",
            value=f"host{i}.example.com",
            value_normalized=f"host{i}.example.com",
            fingerprint=f"fp-pagination-{i}",
            severity="info",
            first_seen_at=now,
            last_seen_at=now,
        )
        created_ids.add(f.id)

    seen_ids: list[UUID] = []
    cursor: str | None = None

    while True:
        items, cursor = await repo.list_by_run(run.id, limit=2, cursor=cursor)
        for item in items:
            seen_ids.append(item.id)
        if cursor is None:
            break

    assert len(seen_ids) == 6
    assert set(seen_ids) == created_ids
    assert len(set(seen_ids)) == len(seen_ids)


# ===========================================================================
# 4. Unique Constraints
# ===========================================================================


def test_target_uniqueness_scoped_to_tenant(sync_db_session, two_tenants_in_db):
    tenant_a, tenant_b = two_tenants_in_db

    t1 = Target(
        id=uuid4(),
        tenant_id=tenant_a.id,
        kind="domain",
        value="Example.com",
        value_normalized="example.com",
    )
    sync_db_session.add(t1)
    sync_db_session.commit()

    # Duplicate under same tenant must fail
    t2 = Target(
        id=uuid4(),
        tenant_id=tenant_a.id,
        kind="domain",
        value="example.COM",
        value_normalized="example.com",
    )
    sync_db_session.add(t2)
    with pytest.raises(IntegrityError):
        sync_db_session.commit()
    sync_db_session.rollback()

    # Same target under different tenant must SUCCEED
    t3 = Target(
        id=uuid4(),
        tenant_id=tenant_b.id,
        kind="domain",
        value="example.com",
        value_normalized="example.com",
    )
    sync_db_session.add(t3)
    sync_db_session.commit()
    assert t3.id is not None


def test_finding_fingerprint_uniqueness_scoped_to_tenant(
    sync_db_session, two_tenants_in_db
):
    tenant_a, tenant_b = two_tenants_in_db
    now = datetime.now(UTC)

    target_a = Target(
        id=uuid4(),
        tenant_id=tenant_a.id,
        kind="domain",
        value="a.com",
        value_normalized="a.com",
    )
    target_b = Target(
        id=uuid4(),
        tenant_id=tenant_b.id,
        kind="domain",
        value="b.com",
        value_normalized="b.com",
    )
    sync_db_session.add_all([target_a, target_b])
    sync_db_session.commit()

    f1 = Finding(
        id=uuid4(),
        tenant_id=tenant_a.id,
        target_id=target_a.id,
        kind="subdomain",
        value="sub.a.com",
        value_normalized="sub.a.com",
        fingerprint="shared-fingerprint-hex-value-64chars",
        severity="low",
        first_seen_at=now,
        last_seen_at=now,
    )
    sync_db_session.add(f1)
    sync_db_session.commit()

    # Duplicate fingerprint for same tenant must fail
    f2 = Finding(
        id=uuid4(),
        tenant_id=tenant_a.id,
        target_id=target_a.id,
        kind="subdomain",
        value="sub2.a.com",
        value_normalized="sub2.a.com",
        fingerprint="shared-fingerprint-hex-value-64chars",
        severity="medium",
        first_seen_at=now,
        last_seen_at=now,
    )
    sync_db_session.add(f2)
    with pytest.raises(IntegrityError):
        sync_db_session.commit()
    sync_db_session.rollback()

    # Same fingerprint for different tenant must SUCCEED
    f3 = Finding(
        id=uuid4(),
        tenant_id=tenant_b.id,
        target_id=target_b.id,
        kind="subdomain",
        value="sub.b.com",
        value_normalized="sub.b.com",
        fingerprint="shared-fingerprint-hex-value-64chars",
        severity="high",
        first_seen_at=now,
        last_seen_at=now,
    )
    sync_db_session.add(f3)
    sync_db_session.commit()
    assert f3.id is not None


# ===========================================================================
# 5. Domain Query & Filter Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_target_domain_queries(fake_async_session, two_tenants_in_db):
    tenant_a, _ = two_tenants_in_db
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    repo = TargetRepository(fake_async_session)

    t1 = await repo.create(
        kind="domain",
        value="Example.COM.",
        value_normalized="example.com",
        is_active=True,
    )
    t2 = await repo.create(
        kind="ipv4",
        value="1.2.3.4",
        value_normalized="1.2.3.4",
        is_active=False,
    )

    # get_by_kind_and_value
    found = await repo.get_by_kind_and_value("domain", "example.com")
    assert found is not None
    assert found.id == t1.id

    assert await repo.get_by_kind_and_value("domain", "non-existent.com") is None

    # list with kind filter
    domains, _ = await repo.list(kind="domain")
    assert len(domains) == 1
    assert domains[0].id == t1.id

    # list with is_active filter
    active_only, _ = await repo.list(is_active=True)
    assert len(active_only) == 1
    assert active_only[0].id == t1.id

    inactive_only, _ = await repo.list(is_active=False)
    assert len(inactive_only) == 1
    assert inactive_only[0].id == t2.id


@pytest.mark.asyncio
async def test_scan_run_domain_queries(fake_async_session, two_tenants_in_db):
    tenant_a, _ = two_tenants_in_db
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    target = await TargetRepository(fake_async_session).create(
        kind="domain", value="test.com", value_normalized="test.com"
    )
    run_repo = ScanRunRepository(fake_async_session)

    r1 = await run_repo.create(target_id=target.id, max_attempts=3, status="succeeded")
    r2 = await run_repo.create(target_id=target.id, max_attempts=3, status="running")

    # get_latest_for_target
    latest = await run_repo.get_latest_for_target(target.id)
    assert latest is not None
    assert latest.id == r2.id

    # list with status filter
    succeeded, _ = await run_repo.list(status="succeeded")
    assert len(succeeded) == 1
    assert succeeded[0].id == r1.id


@pytest.mark.asyncio
async def test_finding_domain_queries(fake_async_session, two_tenants_in_db):
    tenant_a, _ = two_tenants_in_db
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    target = await TargetRepository(fake_async_session).create(
        kind="domain", value="test.com", value_normalized="test.com"
    )
    run = await ScanRunRepository(fake_async_session).create(
        target_id=target.id, max_attempts=3
    )
    repo = FindingRepository(fake_async_session)
    now = datetime.now(UTC)

    f1 = await repo.create(
        target_id=target.id,
        last_seen_run_id=run.id,
        kind="subdomain",
        value="admin.test.com",
        value_normalized="admin.test.com",
        fingerprint="fp-test-domain-1",
        severity="critical",
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    f2 = await repo.create(
        target_id=target.id,
        last_seen_run_id=run.id,
        kind="credential",
        value="user@test.com",
        value_normalized="user@test.com",
        fingerprint="fp-test-domain-2",
        severity="low",
        status="resolved",
        first_seen_at=now,
        last_seen_at=now,
    )

    # get_by_fingerprint
    found = await repo.get_by_fingerprint("fp-test-domain-1")
    assert found is not None
    assert found.id == f1.id

    assert await repo.get_by_fingerprint("non-existent") is None

    # list with kind filter
    subdomains, _ = await repo.list(kind="subdomain")
    assert len(subdomains) == 1
    assert subdomains[0].id == f1.id

    # list with severity filter
    critical, _ = await repo.list(severity="critical")
    assert len(critical) == 1
    assert critical[0].id == f1.id

    # list with status filter
    resolved, _ = await repo.list(status="resolved")
    assert len(resolved) == 1
    assert resolved[0].id == f2.id
