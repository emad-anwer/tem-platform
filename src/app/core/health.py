from fastapi import APIRouter, Response, status

from app.core.db import check_db_connection

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness(response: Response) -> dict[str, str]:
    db_connected = await check_db_connection()
    if not db_connected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "message": "Database connection failed"}
    return {"status": "ok"}
