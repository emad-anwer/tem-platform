import structlog
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = structlog.get_logger()


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Clear any leftover context from previous requests
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        try:
            logger.info(
                "request_started",
                method=request.method,
                path=request.url.path,
            )

            response = await call_next(request)

            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request_finished",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )

            return response
        finally:
            structlog.contextvars.clear_contextvars()
