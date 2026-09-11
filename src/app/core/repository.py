"""Database access for shared platform entities."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.context import get_current_principal
from app.core.auth.principal import Principal, Role
from app.core.models import Finding, ScanRun, Target, Tenant, TenantOwnedMixin
from app.core.pagination import decode_cursor, encode_cursor

T = TypeVar("T", bound=TenantOwnedMixin)
MAX_SCAN_RUN_ERROR_MESSAGE_LENGTH = 2000
_INVALID_CURSOR = "Invalid cursor."
_LIMIT_MUST_BE_POSITIVE = "limit must be greater than 0."


class MissingTenantContextError(RuntimeError):
    """Raised when an operation requires a tenant context but none is present."""


def _coerce_uuid(value: UUID | str, param_name: str) -> UUID:
    """Coerce a UUID | str parameter to UUID for safe comparison against UUID columns.

    asyncpg returns empty results when a string is compared directly against a
    UUID column; normalising here keeps repository signatures ergonomic while
    ensuring correct query behaviour.
    """
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid UUID for {param_name!r}.") from exc


class CreatedAtIdCursor:
    """Shared created_at + id cursor implementation for tenant-scoped repositories.

    Provides the standard cursor column trio (created_at, id) used by
    TargetRepository, ScanRunRepository, and FindingRepository, eliminating
    triplicated encode/decode logic.
    """

    @staticmethod
    def columns(model: type[Any]) -> tuple[Any, ...]:
        """Return the cursor column tuple for a model."""
        return (model.created_at, model.id)

    @staticmethod
    def encode(entity: Any) -> str:
        """Encode an entity's cursor values into an opaque string."""
        return encode_cursor([entity.created_at.isoformat(), str(entity.id)])

    @staticmethod
    def decode(cursor: str) -> tuple[datetime, UUID]:
        """Decode an opaque cursor string back into (created_at, id)."""
        values = decode_cursor(cursor)
        if len(values) != 2:
            raise ValueError(_INVALID_CURSOR)
        created_at_str, id_str = values
        try:
            return datetime.fromisoformat(created_at_str), UUID(id_str)
        except (ValueError, TypeError) as exc:
            raise ValueError(_INVALID_CURSOR) from exc


class TenantScopedRepository(Generic[T]):
    """Base repository for models owned by a tenant.

    - Every read automatically filters by `WHERE tenant_id = <context tenant>`.
    - Every create automatically stamps `tenant_id` from the context.
    - Every update and delete verifies ownership before acting.
    - Constructed without a context or used when the context is empty -> raises loudly.
    """

    model: type[Any]

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
        entity_uuid = _coerce_uuid(entity_id, "entity_id")
        stmt = self._scope_select(select(self.model)).where(
            self.model.id == entity_uuid
        )
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
            raise ValueError(_LIMIT_MUST_BE_POSITIVE)

        columns = self._cursor_columns()

        stmt = self._scope_select(select(self.model)).order_by(*columns)

        if cursor is not None:
            values = self._decode_cursor(cursor)

            if len(values) != len(columns):
                raise ValueError(_INVALID_CURSOR)

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
            raise ValueError(_INVALID_CURSOR)

        name, id_str = values

        try:
            return name, UUID(id_str)
        except (ValueError, TypeError) as exc:
            raise ValueError(_INVALID_CURSOR) from exc

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

    async def list(  # noqa: S2638 -- filtered repository methods intentionally extend the base query API.
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        principal: Principal | None = None,
    ) -> tuple[Sequence[Tenant], str | None]:
        """List tenants. Non-admins only ever see their own tenant (one row);
        PLATFORM_ADMIN sees the full platform list — no other route exposes
        full-platform enumeration.
        """
        if principal is None:
            raise MissingTenantContextError(
                "TenantRepository.list() requires a Principal for tenant scoping."
            )
        stmt = select(Tenant).order_by(Tenant.name, Tenant.id).limit(limit + 1)
        if principal.role != Role.PLATFORM_ADMIN:
            stmt = stmt.where(Tenant.id == principal.tenant_id)
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


class TargetRepository(TenantScopedRepository[Target]):
    """Tenant-scoped repository for Targets."""

    model = Target

    def _cursor_columns(self) -> tuple[Any, ...]:
        return CreatedAtIdCursor.columns(self.model)

    def _encode_cursor(self, entity: Target) -> str:
        return CreatedAtIdCursor.encode(entity)

    def _decode_cursor(self, cursor: str) -> tuple[datetime, UUID]:
        return CreatedAtIdCursor.decode(cursor)

    async def get_by_kind_and_value(
        self,
        kind: str,
        value_normalized: str,
    ) -> Target | None:
        """Lookup target by unique (tenant_id, kind, value_normalized)."""
        stmt = self._scope_select(select(self.model)).where(
            self.model.kind == kind,
            self.model.value_normalized == value_normalized,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        kind: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[Sequence[Target], str | None]:
        if limit <= 0:
            raise ValueError(_LIMIT_MUST_BE_POSITIVE)

        columns = self._cursor_columns()
        stmt = self._scope_select(select(self.model)).order_by(*columns)

        if kind is not None:
            stmt = stmt.where(self.model.kind == kind)
        if is_active is not None:
            stmt = stmt.where(self.model.is_active == is_active)

        if cursor is not None:
            values = self._decode_cursor(cursor)
            if len(values) != len(columns):
                raise ValueError(_INVALID_CURSOR)
            stmt = stmt.where(tuple_(*columns) > tuple(values))

        result = await self._session.execute(stmt.limit(limit + 1))
        items = list(result.scalars().all())

        if len(items) <= limit:
            return items, None

        items = items[:limit]
        return items, self._encode_cursor(items[-1])


class ScanRunRepository(TenantScopedRepository[ScanRun]):
    """Tenant-scoped repository for ScanRuns."""

    model = ScanRun

    @staticmethod
    def _truncate_error_message(attributes: dict[str, Any]) -> None:
        error_message = attributes.get("error_message")
        if error_message is not None:
            attributes["error_message"] = error_message[
                :MAX_SCAN_RUN_ERROR_MESSAGE_LENGTH
            ]

    async def create(self, **attributes: Any) -> ScanRun:
        self._truncate_error_message(attributes)
        return await super().create(**attributes)

    async def update(self, entity_id: UUID | str, **attributes: Any) -> ScanRun | None:
        self._truncate_error_message(attributes)
        return await super().update(entity_id, **attributes)

    def _cursor_columns(self) -> tuple[Any, ...]:
        return CreatedAtIdCursor.columns(self.model)

    def _encode_cursor(self, entity: ScanRun) -> str:
        return CreatedAtIdCursor.encode(entity)

    def _decode_cursor(self, cursor: str) -> tuple[datetime, UUID]:
        return CreatedAtIdCursor.decode(cursor)

    async def get_latest_for_target(
        self,
        target_id: UUID | str,
    ) -> ScanRun | None:
        """Retrieve the most recent scan run for a given target."""
        target_uuid = _coerce_uuid(target_id, "target_id")
        stmt = (
            self._scope_select(select(self.model))
            .where(self.model.target_id == target_uuid)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(  # noqa: S2638 -- filtered repository methods intentionally extend the base query API.
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        target_id: UUID | str | None = None,
        status: str | None = None,
    ) -> tuple[Sequence[ScanRun], str | None]:
        if limit <= 0:
            raise ValueError(_LIMIT_MUST_BE_POSITIVE)

        columns = self._cursor_columns()
        stmt = self._scope_select(select(self.model)).order_by(*columns)

        if target_id is not None:
            stmt = stmt.where(
                self.model.target_id == _coerce_uuid(target_id, "target_id")
            )
        if status is not None:
            stmt = stmt.where(self.model.status == status)

        if cursor is not None:
            values = self._decode_cursor(cursor)
            if len(values) != len(columns):
                raise ValueError(_INVALID_CURSOR)
            stmt = stmt.where(tuple_(*columns) > tuple(values))

        result = await self._session.execute(stmt.limit(limit + 1))
        items = list(result.scalars().all())

        if len(items) <= limit:
            return items, None

        items = items[:limit]
        return items, self._encode_cursor(items[-1])

    async def list_by_target(
        self,
        target_id: UUID | str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[Sequence[ScanRun], str | None]:
        return await self.list(limit=limit, cursor=cursor, target_id=target_id)


class FindingRepository(TenantScopedRepository[Finding]):
    """Tenant-scoped repository for Findings."""

    model = Finding

    def _cursor_columns(self) -> tuple[Any, ...]:
        return CreatedAtIdCursor.columns(self.model)

    def _encode_cursor(self, entity: Finding) -> str:
        return CreatedAtIdCursor.encode(entity)

    def _decode_cursor(self, cursor: str) -> tuple[datetime, UUID]:
        return CreatedAtIdCursor.decode(cursor)

    async def get_by_fingerprint(
        self,
        fingerprint: str,
    ) -> Finding | None:
        """Lookup finding by unique (tenant_id, fingerprint)."""
        stmt = self._scope_select(select(self.model)).where(
            self.model.fingerprint == fingerprint
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(  # noqa: S2638 -- filtered repository methods intentionally extend the base query API.
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        target_id: UUID | str | None = None,
        run_id: UUID | str | None = None,
        kind: str | None = None,
        severity: str | None = None,
        status: str | None = None,
    ) -> tuple[Sequence[Finding], str | None]:
        if limit <= 0:
            raise ValueError(_LIMIT_MUST_BE_POSITIVE)

        columns = self._cursor_columns()
        stmt = self._scope_select(select(self.model)).order_by(*columns)

        if target_id is not None:
            stmt = stmt.where(
                self.model.target_id == _coerce_uuid(target_id, "target_id")
            )
        if run_id is not None:
            stmt = stmt.where(
                self.model.last_seen_run_id == _coerce_uuid(run_id, "run_id")
            )
        if kind is not None:
            stmt = stmt.where(self.model.kind == kind)
        if severity is not None:
            stmt = stmt.where(self.model.severity == severity)
        if status is not None:
            stmt = stmt.where(self.model.status == status)

        if cursor is not None:
            values = self._decode_cursor(cursor)
            if len(values) != len(columns):
                raise ValueError(_INVALID_CURSOR)
            stmt = stmt.where(tuple_(*columns) > tuple(values))

        result = await self._session.execute(stmt.limit(limit + 1))
        items = list(result.scalars().all())

        if len(items) <= limit:
            return items, None

        items = items[:limit]
        return items, self._encode_cursor(items[-1])

    async def list_by_target(
        self,
        target_id: UUID | str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[Sequence[Finding], str | None]:
        return await self.list(limit=limit, cursor=cursor, target_id=target_id)

    async def list_by_run(
        self,
        run_id: UUID | str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[Sequence[Finding], str | None]:
        return await self.list(limit=limit, cursor=cursor, run_id=run_id)
