from fastapi import APIRouter, Response, status
from pydantic import BaseModel


from app.core.db import check_db_connection
from app.core.redis import check_redis_connection


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(HealthResponse):
    message: str | None = None
    db: str | None = None
    redis: str | None = None


router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=ReadinessResponse, response_model_exclude_none=True)
async def readiness(response: Response) -> ReadinessResponse:
    db_connected = await check_db_connection()
    redis_connected = await check_redis_connection()
    if not db_connected or not redis_connected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
          status="unavailable", 
          message="Service dependencies unhealthy", 
          db="ok" if db_connected else "unavailable",
          redis="ok" if redis_connected else "unavailable"
        )
    return ReadinessResponse(status="ok")

