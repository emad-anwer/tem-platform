from __future__ import annotations

from uuid import UUID
from fastapi import APIRouter, Query, Request, status, Depends, Response

from app.core.errors import COMMON_ERROR_RESPONSES, BadRequestError
from app.core.pipeline.schemas import (
    CollectionLinks,
    TargetCollectionDocument,
    TargetCreateRequest,
    TargetDocument,
    TargetResource,
)
from app.core.pipeline.service import PipelineService, get_pipeline_service

router = APIRouter(tags=["pipeline"], responses=COMMON_ERROR_RESPONSES)


_TARGETS_PARAMS = {"size", "cursor"}
_FINDINGS_PARAMS = {"size", "cursor", "target_id", "scan_run_id"}


def _check_known_params(request: Request, allowed: set[str]) -> None:
    unknown = set(request.query_params.keys()) - allowed
    if unknown:
        raise BadRequestError(
            detail=f"Unknown query parameter(s): {', '.join(sorted(unknown))}"
        )


def _parse_size(size: int) -> int:
    if size < 1 or size > 100:
        raise BadRequestError(detail="size must be between 1 and 100.")
    return size


def _links(request: Request, next_cursor: str | None) -> CollectionLinks:
    next_link = None
    if next_cursor:
        next_link = str(request.url.include_query_params(cursor=next_cursor))
    return CollectionLinks(self=str(request.url), next=next_link)


@router.post(
    "/api/v1/targets",
    status_code=status.HTTP_201_CREATED,
    response_model=TargetDocument,
    summary="Create a target",
)
async def create_target(
    body: TargetCreateRequest,
    response: Response,
    service: PipelineService = Depends(get_pipeline_service),
) -> TargetDocument:
    target = await service.create_target(kind=body.kind, value=body.value)
    response.headers["Location"] = f"/api/v1/targets/{target.id}"
    return TargetDocument(data=TargetResource.from_model(target))


@router.get(
    "/api/v1/targets",
    response_model=TargetCollectionDocument,
    summary="List targets",
)
async def list_targets(
    request: Request,
    size: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    service: PipelineService = Depends(get_pipeline_service),
) -> TargetCollectionDocument:
    _check_known_params(request, _TARGETS_PARAMS)
    size = _parse_size(size)
    items, next_cursor = await service.list_targets(size=size, cursor=cursor)
    return TargetCollectionDocument(
        data=[TargetResource.from_model(item) for item in items],
        links=_links(request, next_cursor),
    )
