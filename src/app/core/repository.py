"""Database access for shared platform entities."""

import base64
import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Tenant


def encode_tenant_cursor(name: str, tenant_id: UUID) -> str:
    payload = json.dumps([name, str(tenant_id)])
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_tenant_cursor(cursor: str) -> tuple[str, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        name, id_str = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        return name, UUID(id_str)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid cursor.") from exc


class TenantRepository:
    """Persist and retrieve tenants without exposing SQL to service layers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, name: str, slug: str, is_active: bool = True) -> Tenant:
        tenant = Tenant(name=name, slug=slug, is_active=is_active)
        self._session.add(tenant)
        await self._session.commit()
        await self._session.refresh(tenant)
        return tenant

    async def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        result = await self._session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
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
            name, tenant_id = decode_tenant_cursor(cursor)
            stmt = stmt.where(tuple_(Tenant.name, Tenant.id) > (name, tenant_id))

        result = await self._session.execute(stmt)
        items = list(result.scalars().all())

        next_cursor = None
        if len(items) > limit:
            items = items[:limit]
            last = items[-1]
            next_cursor = encode_tenant_cursor(last.name, last.id)

        return items, next_cursor
