from fastapi import APIRouter, Response, status

from app.core.db import check_db_connection
from app.core.redis import check_redis_connection

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness(response: Response) -> dict:
    db_connected = await check_db_connection()
    redis_connected = await check_redis_connection()
    if not db_connected or not redis_connected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unavailable",
            "message": "Service dependencies unhealthy",
            "db": "ok" if db_connected else "unavailable",
            "redis": "ok" if redis_connected else "unavailable",
        }
    return {"status": "ok"}
