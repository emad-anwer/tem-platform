from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import ConflictError
from app.core.models import Tenant
from app.core.repository import TenantRepository


async def get_tenant_service(session: AsyncSession = Depends(get_db)) -> TenantService:
    return TenantService(session)


class TenantService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = TenantRepository(session)

    async def create_tenant(self, *, name: str, slug: str, is_active: bool = True) -> Tenant:
        existing = await self._repository.get_by_slug(slug)
        if existing is not None:
            raise ConflictError(detail=f"Tenant slug '{slug}' already exists.")

        try:
            return await self._repository.create(name=name, slug=slug, is_active=is_active)
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError(detail=f"Tenant slug '{slug}' already exists.") from exc

    async def get_tenant(self, tenant_id: UUID) -> Tenant | None:
        return await self._repository.get_by_id(tenant_id)

    async def list_tenants(
        self, *, limit: int, cursor: str | None = None
    ) -> tuple[list[Tenant], str | None]:
        items, next_cursor = await self._repository.list(limit=limit, cursor=cursor)
        return list(items), next_cursor
