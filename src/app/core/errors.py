import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_BASE_URL = "https://tem-platform.dev/problems"

PROBLEM_REGISTRY: dict[int, tuple[str, str]] = {
    status.HTTP_400_BAD_REQUEST: ("bad-request", "Bad Request"),
    status.HTTP_401_UNAUTHORIZED: ("unauthorized", "Unauthorized"),
    status.HTTP_403_FORBIDDEN: ("forbidden", "Forbidden"),
    status.HTTP_404_NOT_FOUND: ("not-found", "Not Found"),
    status.HTTP_409_CONFLICT: ("conflict", "Conflict"),
    status.HTTP_422_UNPROCESSABLE_ENTITY: ("validation-error", "Validation Error"),
    status.HTTP_429_TOO_MANY_REQUESTS: ("rate-limited", "Too Many Requests"),
    status.HTTP_500_INTERNAL_SERVER_ERROR: ("internal-error", "Internal Server Error"),
    status.HTTP_503_SERVICE_UNAVAILABLE: ("service-unavailable", "Service Unavailable"),
}


def _get_request_id(request: Request) -> str:
    """Resolve request ID from structlog contextvars, request state, header, or generate a fallback."""
    try:
        import structlog

        ctx = structlog.contextvars.get_contextvars()
        if "request_id" in ctx and ctx["request_id"]:
            return str(ctx["request_id"])
    except Exception:
        pass

    if hasattr(request, "state") and hasattr(request.state, "request_id"):
        req_id = getattr(request.state, "request_id")
        if req_id:
            return str(req_id)

    header_id = request.headers.get("x-request-id")
    if header_id:
        return header_id.strip()

    return str(uuid.uuid4())


def _format_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Format Pydantic / FastAPI validation error items into clean field/message objects."""
    formatted: list[dict[str, str]] = []
    for err in errors:
        loc = err.get("loc", ())
        parts = [str(part) for part in loc if part not in ("body",)]
        field = ".".join(parts) if parts else "request"
        msg = err.get("msg", "Invalid value")
        formatted.append({"field": field, "message": msg})
    return formatted


def create_problem_response(
    status_code: int,
    title: str,
    detail: str,
    instance: str,
    slug: str,
    request_id: str,
    errors: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Construct an RFC 9457 compliant problem details JSON response."""
    payload: dict[str, Any] = {
        "type": f"{PROBLEM_BASE_URL}/{slug}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": instance,
        "request_id": request_id,
    }
    if errors is not None:
        payload["errors"] = errors

    response_headers = dict(headers) if headers else {}
    response_headers["x-request-id"] = request_id

    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
        headers=response_headers,
    )


# ----------------------------------------------------------------------
# Custom Exception Hierarchy
# ----------------------------------------------------------------------


class AppError(Exception):
    """Base exception for all application-level errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    slug: str = "internal-error"
    title: str = "Internal Server Error"

    def __init__(
        self,
        detail: str = "An unexpected error occurred.",
        *,
        slug: str | None = None,
        title: str | None = None,
        status_code: int | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if slug is not None:
            self.slug = slug
        if title is not None:
            self.title = title
        if status_code is not None:
            self.status_code = status_code
        self.errors = errors


class BadRequestError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    slug = "bad-request"
    title = "Bad Request"

    def __init__(self, detail: str = "Bad request.", **kwargs: Any) -> None:
        super().__init__(detail, **kwargs)


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    slug = "unauthorized"
    title = "Unauthorized"

    def __init__(
        self, detail: str = "Authentication required.", **kwargs: Any
    ) -> None:
        super().__init__(detail, **kwargs)


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    slug = "forbidden"
    title = "Forbidden"

    def __init__(
        self, detail: str = "Permission denied.", **kwargs: Any
    ) -> None:
        super().__init__(detail, **kwargs)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    slug = "not-found"
    title = "Not Found"

    def __init__(
        self, detail: str = "Resource not found.", **kwargs: Any
    ) -> None:
        super().__init__(detail, **kwargs)


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    slug = "conflict"
    title = "Conflict"

    def __init__(
        self, detail: str = "Resource conflict.", **kwargs: Any
    ) -> None:
        super().__init__(detail, **kwargs)


class ValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    slug = "validation-error"
    title = "Validation Error"

    def __init__(
        self,
        detail: str = "One or more fields failed validation.",
        errors: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(detail, errors=errors, **kwargs)


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    slug = "rate-limited"
    title = "Too Many Requests"

    def __init__(
        self, detail: str = "Rate limit exceeded.", **kwargs: Any
    ) -> None:
        super().__init__(detail, **kwargs)


class InternalError(AppError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    slug = "internal-error"
    title = "Internal Server Error"

    def __init__(
        self, detail: str = "Internal server error.", **kwargs: Any
    ) -> None:
        super().__init__(detail, **kwargs)


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    slug = "service-unavailable"
    title = "Service Unavailable"

    def __init__(
        self, detail: str = "Service temporarily unavailable.", **kwargs: Any
    ) -> None:
        super().__init__(detail, **kwargs)


# ----------------------------------------------------------------------
# Exception Handlers
# ----------------------------------------------------------------------


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    req_id = _get_request_id(request)
    logger.warning(
        "Application error [%s]: %s (status=%d, path=%s, request_id=%s)",
        exc.slug,
        exc.detail,
        exc.status_code,
        request.url.path,
        req_id,
    )
    return create_problem_response(
        status_code=exc.status_code,
        title=exc.title,
        detail=exc.detail,
        instance=request.url.path,
        slug=exc.slug,
        request_id=req_id,
        errors=exc.errors,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError | ValidationError
) -> JSONResponse:
    req_id = _get_request_id(request)
    formatted_errors = _format_validation_errors(exc.errors())
    return create_problem_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        title="Validation Error",
        detail="One or more fields failed validation.",
        instance=request.url.path,
        slug="validation-error",
        request_id=req_id,
        errors=formatted_errors,
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    req_id = _get_request_id(request)
    slug, default_title = PROBLEM_REGISTRY.get(
        exc.status_code, ("internal-error", "HTTP Error")
    )
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    headers = dict(exc.headers) if exc.headers else {}

    return create_problem_response(
        status_code=exc.status_code,
        title=default_title,
        detail=detail,
        instance=request.url.path,
        slug=slug,
        request_id=req_id,
        headers=headers,
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    req_id = _get_request_id(request)
    logger.exception(
        "Unhandled exception processing request (path=%s, request_id=%s): %s",
        request.url.path,
        req_id,
        exc,
    )
    return create_problem_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        title="Internal Server Error",
        detail="An unexpected server error occurred.",
        instance=request.url.path,
        slug="internal-error",
        request_id=req_id,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register RFC 9457 error handlers on the FastAPI application."""
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
