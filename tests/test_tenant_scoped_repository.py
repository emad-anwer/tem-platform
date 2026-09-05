from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import String, create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from app.core.auth.context import (
    clear_current_principal,
    set_current_principal,
)
from app.core.auth.principal import Principal, Role
from app.core.models import Base, TenantOwnedMixin
from app.core.pagination import decode_cursor, encode_cursor
from app.core.repository import MissingTenantContextError, TenantScopedRepository


class DummyTenantOwnedModel(Base, TenantOwnedMixin):
    __tablename__ = "dummy_tenant_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class DummyTenantRepository(TenantScopedRepository[DummyTenantOwnedModel]):
    model = DummyTenantOwnedModel

    def _cursor_columns(self) -> tuple:
        return (self.model.name, self.model.id)

    def _encode_cursor(self, entity: DummyTenantOwnedModel) -> str:
        return encode_cursor([entity.name, str(entity.id)])

    def _decode_cursor(self, cursor: str) -> tuple[str, UUID]:
        values = decode_cursor(cursor)
        if len(values) != 2:
            raise ValueError("Invalid cursor.")
        name, id_str = values
        try:
            return str(name), UUID(id_str)
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid cursor.") from exc


class DummyAsyncSessionWrapper:
    """Synchronous in-memory SQLite wrapper simulating AsyncSession interface for unit tests."""

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


@pytest.mark.asyncio
async def test_repository_raises_loudly_when_constructed_without_context(
    fake_async_session,
):
    """Protects the property that makes everything else safe:

    Constructed without a context, or used when context is empty -> raise loudly.
    Never silently fall back to an unfiltered query.
    """
    clear_current_principal()

    with pytest.raises(MissingTenantContextError) as exc_info:
        TenantScopedRepository(fake_async_session, DummyTenantOwnedModel)

    assert "No tenant context available" in str(exc_info.value)


@pytest.mark.asyncio
async def test_repository_raises_loudly_when_context_is_empty_or_cleared(
    fake_async_session,
):
    tenant_id = uuid4()
    principal = Principal(user_id="user-1", tenant_id=tenant_id, role=Role.OWNER)
    set_current_principal(principal)

    repo = TenantScopedRepository(fake_async_session, DummyTenantOwnedModel)
    assert repo.tenant_id == tenant_id

    # If context is cleared afterwards, tenant_id property check / scoped operations
    repo._tenant_id = None
    with pytest.raises(MissingTenantContextError):
        _ = repo.tenant_id


@pytest.mark.asyncio
async def test_automatic_tenant_stamping_on_create(fake_async_session):
    tenant_id = uuid4()
    principal = Principal(user_id="user-1", tenant_id=tenant_id, role=Role.OWNER)
    set_current_principal(principal)

    repo = TenantScopedRepository(fake_async_session, DummyTenantOwnedModel)
    item = await repo.create(name="My Secure Asset")

    assert item.id is not None
    assert item.name == "My Secure Asset"
    assert item.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_create_overrides_attempted_tenant_spoofing(fake_async_session):
    tenant_id = uuid4()
    spoofed_tenant = uuid4()
    principal = Principal(user_id="user-1", tenant_id=tenant_id, role=Role.OWNER)
    set_current_principal(principal)

    repo = TenantScopedRepository(fake_async_session, DummyTenantOwnedModel)
    item = await repo.create(name="Spoofed Asset", tenant_id=spoofed_tenant)

    assert item.tenant_id == tenant_id
    assert item.tenant_id != spoofed_tenant


@pytest.mark.asyncio
async def test_reads_and_lists_are_scoped_to_context_tenant(fake_async_session):
    tenant_a = uuid4()
    tenant_b = uuid4()

    # Create for Tenant A
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a, role=Role.ANALYST)
    )
    repo_a = DummyTenantRepository(fake_async_session)
    item_a = await repo_a.create(name="Tenant A Asset")

    # Create for Tenant B
    set_current_principal(
        Principal(user_id="user-b", tenant_id=tenant_b, role=Role.ANALYST)
    )
    repo_b = DummyTenantRepository(fake_async_session)
    item_b = await repo_b.create(name="Tenant B Asset")

    # While in Tenant A context, Tenant B item cannot be retrieved or listed
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a, role=Role.ANALYST)
    )
    repo_a_current = DummyTenantRepository(fake_async_session)

    assert await repo_a_current.get_by_id(item_a.id) is not None
    assert await repo_a_current.get_by_id(item_b.id) is None

    items, next_cursor = await repo_a_current.list()
    assert len(items) == 1
    assert items[0].id == item_a.id
    assert next_cursor is None


@pytest.mark.asyncio
async def test_update_and_delete_verify_ownership_before_acting(fake_async_session):
    tenant_a = uuid4()
    tenant_b = uuid4()

    # Tenant B creates an item
    set_current_principal(
        Principal(user_id="user-b", tenant_id=tenant_b, role=Role.OWNER)
    )
    repo_b = TenantScopedRepository(fake_async_session, DummyTenantOwnedModel)
    item_b = await repo_b.create(name="Secret Item")

    # Switch to Tenant A context
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a, role=Role.OWNER)
    )
    repo_a = TenantScopedRepository(fake_async_session, DummyTenantOwnedModel)

    # Attempt to update Tenant B item
    updated = await repo_a.update(item_b.id, name="Hacked Name")
    assert updated is None

    # Attempt to delete Tenant B item
    deleted = await repo_a.delete(item_b.id)
    assert deleted is False

    # Switch back to Tenant B context and verify item is intact
    set_current_principal(
        Principal(user_id="user-b", tenant_id=tenant_b, role=Role.OWNER)
    )
    repo_b_current = TenantScopedRepository(fake_async_session, DummyTenantOwnedModel)
    rechecked = await repo_b_current.get_by_id(item_b.id)
    assert rechecked is not None
    assert rechecked.name == "Secret Item"

    # Successfully update & delete as Tenant B
    updated = await repo_b_current.update(item_b.id, name="New Name")
    assert updated is not None
    assert updated.name == "New Name"

    deleted = await repo_b_current.delete(item_b.id)
    assert deleted is True
    assert await repo_b_current.get_by_id(item_b.id) is None


@pytest.mark.asyncio
async def test_cursor_pagination_forward_navigation(fake_async_session):
    tenant_id = uuid4()
    set_current_principal(Principal(user_id="user-1", tenant_id=tenant_id, role=Role.OWNER))
    repo = DummyTenantRepository(fake_async_session)

    # Create 5 items
    for i in range(1, 6):
        await repo.create(name=f"Asset {i:02d}")

    # Page 1: 2 items
    page_1, cursor_1 = await repo.list(limit=2)
    assert len(page_1) == 2
    assert [x.name for x in page_1] == ["Asset 01", "Asset 02"]
    assert cursor_1 is not None

    # Page 2: 2 items using cursor_1
    page_2, cursor_2 = await repo.list(limit=2, cursor=cursor_1)
    assert len(page_2) == 2
    assert [x.name for x in page_2] == ["Asset 03", "Asset 04"]
    assert cursor_2 is not None

    # Page 3: 1 remaining item
    page_3, cursor_3 = await repo.list(limit=2, cursor=cursor_2)
    assert len(page_3) == 1
    assert [x.name for x in page_3] == ["Asset 05"]
    assert cursor_3 is None
