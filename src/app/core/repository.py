"""Database access for shared platform entities."""

from collections.abc import Sequence
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.context import get_current_principal
from app.core.models import Tenant
from app.core.pagination import decode_cursor, encode_cursor

T = TypeVar("T")


class MissingTenantContextError(RuntimeError):
    """Raised when an operation requires a tenant context but none is present."""


class TenantScopedRepository(Generic[T]):
    """Base repository for models owned by a tenant.

    - Every read automatically filters by `WHERE tenant_id = <context tenant>`.
    - Every create automatically stamps `tenant_id` from the context.
    - Every update and delete verifies ownership before acting.
    - Constructed without a context or used when the context is empty -> raises loudly.
    """

    model: type[T]

    def __init__(
        self,
        session: AsyncSession,
        model: type[T] | None = None,
        *,
        tenant_id: UUID | None = None,
    ) -> None:
        self._session = session
        if model is not None:
            self.model = model
        elif not hasattr(self, "model"):
            raise ValueError(
                "TenantScopedRepository must be provided a model class or define `model` attribute."
            )

        # Resolve tenant_id: either explicitly provided or from request/task principal context
        if tenant_id is not None:
            self._tenant_id = tenant_id
        else:
            try:
                principal = get_current_principal()
                if not principal or not principal.tenant_id:
                    raise MissingTenantContextError(
                        "No tenant context available. TenantScopedRepository requires an active tenant context."
                    )
                self._tenant_id = principal.tenant_id
            except Exception as exc:
                if isinstance(exc, MissingTenantContextError):
                    raise
                raise MissingTenantContextError(
                    "No tenant context available. TenantScopedRepository requires an active tenant context."
                ) from exc

    @property
    def tenant_id(self) -> UUID:
        """The resolved tenant UUID."""
        if not self._tenant_id:
            raise MissingTenantContextError(
                "Empty or missing tenant context in repository."
            )
        return self._tenant_id

    def _scope_select(self, stmt: Any) -> Any:
        """Apply WHERE tenant_id = <context tenant> to a select statement."""
        return stmt.where(self.model.tenant_id == self.tenant_id)

    async def get_by_id(self, entity_id: UUID | str) -> T | None:
        """Retrieve a single entity by its primary key, scoped to the current tenant."""
        stmt = self._scope_select(select(self.model)).where(self.model.id == entity_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    def _cursor_columns(self) -> tuple[Any, ...]:
        raise NotImplementedError

    def _encode_cursor(self, entity: T) -> str:
        raise NotImplementedError

    def _decode_cursor(
        self,
        cursor: str,
    ) -> tuple[Any, ...]:
        raise NotImplementedError

    async def list(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[Sequence[T], str | None]:

        if limit <= 0:
            raise ValueError("limit must be greater than 0.")

        columns = self._cursor_columns()

        stmt = self._scope_select(select(self.model)).order_by(*columns)

        if cursor is not None:
            values = self._decode_cursor(cursor)

            if len(values) != len(columns):
                raise ValueError("Invalid cursor.")

            stmt = stmt.where(tuple_(*columns) > tuple(values))

        result = await self._session.execute(stmt.limit(limit + 1))

        items = list(result.scalars().all())

        if len(items) <= limit:
            return items, None

        items = items[:limit]

        return items, self._encode_cursor(items[-1])

    async def create(self, **attributes: Any) -> T:
        """Create a new model instance, automatically stamping tenant_id from context."""
        # Enforce or override tenant_id from context to prevent cross-tenant spoofing
        attributes["tenant_id"] = self.tenant_id
        instance = self.model(**attributes)
        self._session.add(instance)
        await self._session.commit()
        await self._session.refresh(instance)
        return instance

    async def update(self, entity_id: UUID | str, **attributes: Any) -> T | None:
        """Update an entity after verifying ownership."""
        # tenant_id cannot be changed
        attributes.pop("tenant_id", None)
        entity = await self.get_by_id(entity_id)
        if entity is None:
            return None

        for key, value in attributes.items():
            setattr(entity, key, value)

        self._session.add(entity)
        await self._session.commit()
        await self._session.refresh(entity)
        return entity

    async def delete(self, entity_id: UUID | str) -> bool:
        """Delete an entity after verifying ownership."""
        entity = await self.get_by_id(entity_id)
        if entity is None:
            return False

        await self._session.delete(entity)
        await self._session.commit()
        return True


class TenantRepository:
    """Persist and retrieve tenants without exposing SQL to service layers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _encode_cursor(self, tenant: Tenant) -> str:
        return encode_cursor(
            [
                tenant.name,
                str(tenant.id),
            ]
        )

    def _decode_cursor(self, cursor: str) -> tuple[str, UUID]:
        values = decode_cursor(cursor)

        if len(values) != 2:
            raise ValueError("Invalid cursor.")

        name, id_str = values

        try:
            return name, UUID(id_str)
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid cursor.") from exc

    async def create(
        self,
        *,
        name: str,
        slug: str,
        is_active: bool = True,
        zitadel_org_id: str | None = None,
    ) -> Tenant:
        tenant = Tenant(
            name=name,
            slug=slug,
            is_active=is_active,
            zitadel_org_id=zitadel_org_id,
        )
        self._session.add(tenant)
        await self._session.commit()
        await self._session.refresh(tenant)
        return tenant

    async def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        result = await self._session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def get_by_zitadel_org_id(self, zitadel_org_id: str) -> Tenant | None:
        result = await self._session.execute(
            select(Tenant).where(Tenant.zitadel_org_id == zitadel_org_id)
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Tenant | None:
        result = await self._session.execute(select(Tenant).where(Tenant.slug == slug))
        return result.scalar_one_or_none()

    async def list(
        self, *, limit: int = 20, cursor: str | None = None
    ) -> tuple[Sequence[Tenant], str | None]:
        stmt = select(Tenant).order_by(Tenant.name, Tenant.id).limit(limit + 1)
        if cursor is not None:
            name, tenant_id = self._decode_cursor(cursor)
            stmt = stmt.where(tuple_(Tenant.name, Tenant.id) > (name, tenant_id))

        result = await self._session.execute(stmt)
        items = list(result.scalars().all())

        next_cursor = None
        if len(items) > limit:
            items = items[:limit]
            last = items[-1]
            next_cursor = self._encode_cursor(last)

        return items, next_cursor
