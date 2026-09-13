from __future__ import annotations

from uuid import UUID
from fastapi import APIRouter, status, Depends, Response

from app.core.errors import COMMON_ERROR_RESPONSES
from app.core.pipeline.schemas import (
    TargetCreateRequest,
    TargetDocument,
    TargetResource,
)
from app.core.pipeline.service import PipelineService, get_pipeline_service

router = APIRouter(tags=["pipeline"], responses=COMMON_ERROR_RESPONSES)


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
