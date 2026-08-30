"""Database access for shared platform entities."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Tenant


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
        self, *, limit: int = 20, offset: int = 0
    ) -> tuple[Sequence[Tenant], int]:
        total_result = await self._session.execute(
            select(func.count(Tenant.id))
        )
        total = total_result.scalar_one()

        result = await self._session.execute(
            select(Tenant)
            .order_by(Tenant.name)
            .limit(limit)
            .offset(offset)
        )

        return result.scalars().all(), total