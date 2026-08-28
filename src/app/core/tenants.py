from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.models import Tenant

router = APIRouter(prefix="/api/v1", tags=["tenants"])


class TenantCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        if not value:
            raise ValueError("slug is required")
        if not value.islower():
            raise ValueError("slug must be lowercase")
        if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in value):
            raise ValueError("slug may only contain lowercase letters, numbers, and hyphens")
        if value.startswith("-") or value.endswith("-"):
            raise ValueError("slug must not start or end with a hyphen")
        return value


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime


class TenantListResponse(BaseModel):
    items: list[TenantResponse]
    pagination: dict[str, int]


async def get_tenant_service(session: Annotated[AsyncSession, Depends(get_db)]) -> "TenantService":
    return TenantService(session)


class TenantService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_tenant(self, *, name: str, slug: str, is_active: bool = True) -> Tenant:
        existing = await self._session.execute(
            select(Tenant).where(Tenant.slug == slug)
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError(detail=f"Tenant slug '{slug}' already exists.")

        tenant = Tenant(name=name, slug=slug, is_active=is_active)
        self._session.add(tenant)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError(detail=f"Tenant slug '{slug}' already exists.") from exc
        await self._session.refresh(tenant)
        return tenant

    async def get_tenant(self, tenant_id: UUID) -> Tenant | None:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one_or_none()

    async def list_tenants(self, *, limit: int, offset: int) -> tuple[list[Tenant], int]:
        total = await self._session.scalar(select(Tenant.id).count())
        result = await self._session.execute(
            select(Tenant).order_by(Tenant.name).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), total or 0


@router.post(
    "/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Tenant created"},
        409: {"description": "Duplicate tenant slug"},
        422: {"description": "Validation failed"},
    },
)
async def create_tenant(
    payload: TenantCreateRequest,
    response: Response,
    service: Annotated[TenantService, Depends(get_tenant_service)],
) -> TenantResponse:
    try:
        tenant = await service.create_tenant(name=payload.name, slug=payload.slug)
    except ValueError as exc:
        raise ConflictError(detail=str(exc)) from exc

    tenant_id = getattr(tenant, "id", None) or tenant["id"]
    response.headers["Location"] = f"/api/v1/tenants/{tenant_id}"
    return TenantResponse.model_validate(tenant)


@router.get(
    "/tenants",
    response_model=TenantListResponse,
    responses={200: {"description": "Tenant list"}},
)
async def list_tenants(
    service: Annotated[TenantService, Depends(get_tenant_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TenantListResponse:
    items, total = await service.list_tenants(limit=limit, offset=offset)
    payload_items = [TenantResponse.model_validate(item) for item in items]
    return TenantListResponse(
        items=payload_items,
        pagination={"limit": limit, "offset": offset, "total": total},
    )


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantResponse,
    responses={200: {"description": "Tenant retrieved"}, 404: {"description": "Tenant not found"}},
)
async def get_tenant(
    tenant_id: UUID,
    service: Annotated[TenantService, Depends(get_tenant_service)],
) -> TenantResponse:
    tenant = await service.get_tenant(tenant_id)
    if tenant is None:
        raise NotFoundError(detail=f"Tenant with id '{tenant_id}' does not exist.")
    return TenantResponse.model_validate(tenant)
