from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from typing import Annotated

from app.core.errors import ConflictError, NotFoundError
from app.core.schemas import TenantCreateRequest, TenantListResponse, TenantResponse
from app.core.service import TenantService, get_tenant_service

router = APIRouter(prefix="/api/v1", tags=["tenants"])


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

    tenant_id = getattr(tenant, "id", None)
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
