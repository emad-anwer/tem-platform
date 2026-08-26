from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.core.db import check_db_connection


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(HealthResponse):
    message: str | None = None


router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=ReadinessResponse, response_model_exclude_none=True)
async def readiness(response: Response) -> ReadinessResponse:
    db_connected = await check_db_connection()
    if not db_connected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="unavailable", message="Database connection failed")
    return ReadinessResponse(status="ok")
