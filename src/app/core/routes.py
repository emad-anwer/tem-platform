from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.auth.permissions import Permission, require_permission
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.core.schemas import (
    TenantCollectionDocument,
    TenantCreateRequest,
    TenantDocument,
    TenantResource,
)
from app.core.service import TenantService, get_tenant_service

router = APIRouter(prefix="/api/v1", tags=["tenants"])


@router.post(
    "/tenants",
    response_model=TenantDocument,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(Permission.TENANT_CREATE))],
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
) -> TenantDocument:
    try:
        tenant = await service.create_tenant(name=payload.name, slug=payload.slug)
    except ValueError as exc:
        raise ConflictError(detail=str(exc)) from exc

    tenant_id = getattr(tenant, "id", None)
    response.headers["Location"] = f"/api/v1/tenants/{tenant_id}"
    return TenantDocument(data=TenantResource.from_tenant(tenant))


@router.get(
    "/tenants",
    response_model=TenantCollectionDocument,
    dependencies=[Depends(require_permission(Permission.TENANT_READ))],
    responses={
        200: {"description": "Tenant list"},
        400: {"description": "Invalid cursor"},
    },
)
async def list_tenants(
    request: Request,
    service: Annotated[TenantService, Depends(get_tenant_service)],
    limit: Annotated[int, Query(ge=1, le=100, alias="size")] = 20,
    cursor: Annotated[str | None, Query(alias="cursor")] = None,
) -> TenantCollectionDocument:
    try:
        items, next_cursor = await service.list_tenants(limit=limit, cursor=cursor)
    except ValueError as exc:
        raise BadRequestError(detail="Invalid cursor.") from exc

    self_query = urlencode({"size": limit, **({"cursor": cursor} if cursor else {})})
    next_link = None
    if next_cursor is not None:
        next_query = urlencode({"size": limit, "cursor": next_cursor})
        next_link = f"{request.url.path}?{next_query}"

    return TenantCollectionDocument(
        data=[TenantResource.from_tenant(item) for item in items],
        links={"self": f"{request.url.path}?{self_query}", "next": next_link},
    )


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantDocument,
    dependencies=[Depends(require_permission(Permission.TENANT_READ))],
    responses={
        200: {"description": "Tenant retrieved"},
        404: {"description": "Tenant not found"},
    },
)
async def get_tenant(
    tenant_id: UUID,
    service: Annotated[TenantService, Depends(get_tenant_service)],
) -> TenantDocument:
    tenant = await service.get_tenant(tenant_id)
    if tenant is None:
        raise NotFoundError(detail=f"Tenant with id '{tenant_id}' does not exist.")
    return TenantDocument(data=TenantResource.from_tenant(tenant))
