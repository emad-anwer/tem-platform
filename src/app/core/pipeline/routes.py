from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.auth.permissions import Permission, require_permission
from app.core.errors import COMMON_ERROR_RESPONSES, BadRequestError
from app.core.pipeline.schemas import (
    CollectionLinks,
    FindingCollectionDocument,
    FindingResource,
    ScanRunDocument,
    ScanRunResource,
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
    dependencies=[Depends(require_permission(Permission.TARGET_CREATE))],
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
    items, next_cursor = await service.list_targets(size=size, cursor=cursor)
    return TargetCollectionDocument(
        data=[TargetResource.from_model(item) for item in items],
        links=_links(request, next_cursor),
    )


@router.post(
    "/api/v1/targets/{target_id}/scans",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ScanRunDocument,
    summary="Start a scan against a target",
    dependencies=[Depends(require_permission(Permission.SCAN_START))],
)
async def start_scan(
    target_id: UUID,
    response: Response,
    service: PipelineService = Depends(get_pipeline_service),
) -> ScanRunDocument:
    scan_run = await service.start_scan(target_id=target_id)
    response.headers["Location"] = f"/api/v1/scan_runs/{scan_run.id}"
    return ScanRunDocument(data=ScanRunResource.from_model(scan_run))


@router.get(
    "/api/v1/scan_runs/{scan_run_id}",
    response_model=ScanRunDocument,
    summary="Get scan run state",
)
async def get_scan_run(
    scan_run_id: UUID,
    service: PipelineService = Depends(get_pipeline_service),
) -> ScanRunDocument:
    scan_run = await service.get_scan_run_or_404(scan_run_id)
    return ScanRunDocument(data=ScanRunResource.from_model(scan_run))


@router.get(
    "/api/v1/findings",
    response_model=FindingCollectionDocument,
    summary="List findings",
)
async def list_findings(
    request: Request,
    size: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    target_id: UUID | None = Query(default=None),
    scan_run_id: UUID | None = Query(default=None),
    service: PipelineService = Depends(get_pipeline_service),
) -> FindingCollectionDocument:
    _check_known_params(request, _FINDINGS_PARAMS)
    items, next_cursor = await service.list_findings(
        size=size, cursor=cursor, target_id=target_id, scan_run_id=scan_run_id
    )
    return FindingCollectionDocument(
        data=[FindingResource.from_model(f) for f in items],
        links=_links(request, next_cursor),
    )
