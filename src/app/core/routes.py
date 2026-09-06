from __future__ import annotations

import re
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.core.auth.permissions import Permission, require_permission
from app.core.errors import (
    BadRequestError,
    NotFoundError,
    ServiceUnavailableError,
    UpstreamError,
)
from app.core.provisioning.service import (
    TenantProvisioningService,
    get_tenant_provisioning_service,
)
from app.core.schemas import (
    TenantCollectionDocument,
    TenantCreateRequest,
    TenantDocument,
    TenantResource,
)
from app.core.service import TenantService, get_tenant_service
from app.core.zitadel.client import ZitadelApiError, ZitadelUnavailableError

router = APIRouter(prefix="/api/v1", tags=["tenants"])

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,255}$")


@router.post(
    "/tenants",
    response_model=TenantDocument,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(Permission.TENANT_CREATE))],
)
async def create_tenant(
    payload: TenantCreateRequest,
    response: Response,
    service: Annotated[
        TenantProvisioningService, Depends(get_tenant_provisioning_service)
    ],
    idempotency_key: Annotated[str, Header(..., alias="Idempotency-Key")],
) -> TenantDocument:
    if not IDEMPOTENCY_KEY_PATTERN.match(idempotency_key):
        raise BadRequestError(
            detail="Idempotency-Key must be 1-255 chars of [A-Za-z0-9._-]."
        )

    try:
        tenant, created = await service.provision_tenant(
            name=payload.name, slug=payload.slug, idempotency_key=idempotency_key
        )
    except ZitadelUnavailableError as exc:
        raise ServiceUnavailableError(
            detail="Identity provider is unreachable."
        ) from exc
    except ZitadelApiError as exc:
        raise UpstreamError(detail="Identity provider rejected the request.") from exc

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    response.headers["Location"] = f"/api/v1/tenants/{tenant.id}"
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
