from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import get_principal
from app.core.auth.principal import Principal, Role
from app.core.db import get_db
from app.core.errors import ConflictError, ForbiddenError
from app.core.models import Tenant
from app.core.repository import MissingTenantContextError, TenantRepository


async def get_tenant_service(
    session: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> TenantService:
    return TenantService(session, principal)


class TenantService:
    def __init__(
        self, session: AsyncSession, principal: Principal | None = None
    ) -> None:
        self._session = session
        self._principal = principal
        self._repository = TenantRepository(session)

    def _require_principal(self) -> Principal:
        if self._principal is None:
            raise MissingTenantContextError(
                "This operation requires a Principal. Construct TenantService "
                "via get_tenant_service (Depends(get_principal)) or pass one "
                "explicitly: TenantService(session, principal=...)."
            )
        return self._principal

    async def create_tenant(
        self,
        *,
        name: str,
        slug: str,
        is_active: bool = True,
        zitadel_org_id: str | None = None,
    ) -> Tenant:
        # Unaffected by this fix: provisioning is already PLATFORM_ADMIN-only
        # via TENANT_CREATE at the route layer, and doesn't touch self._principal
        # at all — this is why principal is optional at construction.
        existing = await self._repository.get_by_slug(slug)
        if existing is not None:
            raise ConflictError(detail=f"Tenant slug '{slug}' already exists.")

        try:
            return await self._repository.create(
                name=name,
                slug=slug,
                is_active=is_active,
                zitadel_org_id=zitadel_org_id,
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError(detail=f"Tenant slug '{slug}' already exists.") from exc

    async def get_tenant(self, tenant_id: UUID) -> Tenant | None:
        principal = self._require_principal()
        tenant = await self._repository.get_by_id(tenant_id)
        if tenant is None:
            return None
        if principal.role != Role.PLATFORM_ADMIN and tenant.id != principal.tenant_id:
            raise ForbiddenError(
                detail="Tenant not accessible with the current credentials."
            )
        return tenant

    async def list_tenants(
        self, *, limit: int, cursor: str | None = None
    ) -> tuple[list[Tenant], str | None]:
        principal = self._require_principal()
        items, next_cursor = await self._repository.list(
            limit=limit, cursor=cursor, principal=principal
        )
        return list(items), next_cursor
