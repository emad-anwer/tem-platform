import structlog
import uuid
import time
from starlette.types import ASGIApp, Receive, Scope, Send



class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        logger = structlog.get_logger(__name__)

        raw_request_id = ""
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            raw_request_id = headers.get(b"x-request-id", b"").decode("latin1").strip()
        request_id = raw_request_id if raw_request_id else str(uuid.uuid4())

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = None

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status")
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", request_id.encode("latin1")))
            await send(message)

        try:
            logger.info(
                "request_started",
                method=scope.get("method"),
                path=scope.get("path"),
            )

            await self.app(scope, receive, send_wrapper)

            logger.info(
                "request_finished",
                method=scope.get("method"),
                path=scope.get("path"),
                status_code=status_code,
            )
        except Exception:
            logger.exception("unhandled_exception")
            raise
        finally:
            structlog.contextvars.clear_contextvars()
