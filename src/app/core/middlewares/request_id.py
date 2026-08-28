import re
import structlog
import uuid
import time
from starlette.types import ASGIApp, Receive, Scope, Send

REQUEST_ID_REGEX = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        logger = structlog.get_logger(__name__)

        raw_request_id = ""
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            raw_request_id = headers.get(b"x-request-id", b"").decode("latin1").strip()

        if raw_request_id and REQUEST_ID_REGEX.match(raw_request_id):
            request_id = raw_request_id
        else:
            request_id = str(uuid.uuid4())

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

        start_time = time.perf_counter()
        try:
            logger.info(
                "request_started",
                method=scope.get("method"),
                path=scope.get("path"),
            )

            await self.app(scope, receive, send_wrapper)

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info(
                "request_finished",
                method=scope.get("method"),
                path=scope.get("path"),
                status_code=status_code,
                duration_ms=duration_ms,
            )
        except Exception:
            logger.exception("unhandled_exception")
            raise
        finally:
            structlog.contextvars.clear_contextvars()
