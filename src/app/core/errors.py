import logging
import re
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Whitelist safe characters for request IDs (alphanumeric, hyphens, underscores, dots; max 64 chars)
# Prevents CRLF header injection and log forging (OWASP A03)
REQUEST_ID_REGEX = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
MAX_VALIDATION_ERRORS = 50


# ----------------------------------------------------------------------
# Pydantic Schemas for RFC 9457 & OpenAPI
# ----------------------------------------------------------------------


class ValidationErrorItem(BaseModel):
    """Schema representing an individual field validation error."""

    model_config = ConfigDict(extra="ignore")

    field: str = Field(..., description="Target field that failed validation")
    message: str = Field(..., description="Validation failure explanation")


class ProblemDetails(BaseModel):
    """RFC 9457 Problem Details schema for API error responses."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "type": "https://tem-platform.dev/problems/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": "Resource not found.",
                "instance": "/api/v1/tenants/3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "request_id": "c1f76d90-5b91-4c12-9c3f-8461b2791e80",
            }
        },
    )

    type: str = Field(..., description="URI identifying the problem type")
    title: str = Field(..., description="Short, human-readable summary of problem")
    status: int = Field(..., description="HTTP status code")
    detail: str = Field(..., description="Explanation specific to this occurrence")
    instance: str = Field(..., description="Request path that triggered the error")
    request_id: str = Field(..., description="Unique request tracing identifier")
    errors: list[ValidationErrorItem] | None = Field(
        default=None,
        description="Optional list of field-level validation errors",
    )


# ----------------------------------------------------------------------
# Custom Exception Hierarchy (Single Source of Truth for Error Metadata)
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

    def __init__(self, detail: str = "Authentication required.", **kwargs: Any) -> None:
        super().__init__(detail, **kwargs)


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    slug = "forbidden"
    title = "Forbidden"

    def __init__(self, detail: str = "Permission denied.", **kwargs: Any) -> None:
        super().__init__(detail, **kwargs)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    slug = "not-found"
    title = "Not Found"

    def __init__(self, detail: str = "Resource not found.", **kwargs: Any) -> None:
        super().__init__(detail, **kwargs)


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    slug = "conflict"
    title = "Conflict"

    def __init__(self, detail: str = "Resource conflict.", **kwargs: Any) -> None:
        super().__init__(detail, **kwargs)


class ValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
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

    def __init__(self, detail: str = "Rate limit exceeded.", **kwargs: Any) -> None:
        super().__init__(detail, **kwargs)


class InternalError(AppError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    slug = "internal-error"
    title = "Internal Server Error"

    def __init__(
        self, detail: str = "An unexpected server error occurred.", **kwargs: Any
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


# Single source of truth: derive PROBLEM_REGISTRY and COMMON_ERROR_RESPONSES from AppError classes
APP_ERROR_TYPES: tuple[type[AppError], ...] = (
    BadRequestError,
    UnauthorizedError,
    ForbiddenError,
    NotFoundError,
    ConflictError,
    ValidationError,
    RateLimitedError,
    InternalError,
    ServiceUnavailableError,
)

PROBLEM_REGISTRY: dict[int, tuple[str, str]] = {
    err_cls.status_code: (err_cls.slug, err_cls.title) for err_cls in APP_ERROR_TYPES
}

COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    err_cls.status_code: {"model": ProblemDetails, "description": err_cls.title}
    for err_cls in APP_ERROR_TYPES
}


def _is_safe_request_id(value: str | None) -> bool:
    """Validate request ID against a strict whitelist to prevent header/log injection."""
    if not value or not isinstance(value, str):
        return False
    return bool(REQUEST_ID_REGEX.fullmatch(value.strip()))


def _get_request_id(request: Request) -> str:
    """Resolve and sanitize request ID from structlog, request state, header, or generate a cryptographically strong UUID."""
    # 1. Structlog contextvars
    try:
        import structlog

        ctx = structlog.contextvars.get_contextvars()
        req_id = str(ctx.get("request_id", "")).strip()
        if _is_safe_request_id(req_id):
            return req_id
    except (ImportError, AttributeError, KeyError):
        pass

    # 2. Request state
    if hasattr(request, "state") and hasattr(request.state, "request_id"):
        req_id = str(getattr(request.state, "request_id", "")).strip()
        if _is_safe_request_id(req_id):
            return req_id

    # 3. Client X-Request-ID header (sanitized against injection)
    header_id = request.headers.get("x-request-id")
    if header_id and _is_safe_request_id(header_id):
        return header_id.strip()

    # 4. Secure fallback UUID v4
    return str(uuid.uuid4())


def _format_validation_errors(
    errors: list[dict[str, Any]],
) -> list[ValidationErrorItem]:
    """Format Pydantic / FastAPI validation error items into clean, bounded ValidationErrorItem models."""
    formatted: list[ValidationErrorItem] = []
    # Cap maximum error entries to prevent memory exhaustion DoS (OWASP A04 / A10)
    for err in errors[:MAX_VALIDATION_ERRORS]:
        loc = err.get("loc", ())
        parts = [str(part) for part in loc if part not in ("body",)]
        field = ".".join(parts) if parts else "request"
        msg = str(err.get("msg", "Invalid value"))
        formatted.append(ValidationErrorItem(field=field, message=msg))
    return formatted


def create_problem_response(
    status_code: int,
    title: str,
    detail: str,
    instance: str,
    slug: str,
    request_id: str,
    errors: list[ValidationErrorItem] | list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
    base_url: str | None = None,
) -> JSONResponse:
    """Construct an RFC 9457 compliant problem details JSON response using Pydantic validation."""
    safe_req_id = request_id if _is_safe_request_id(request_id) else str(uuid.uuid4())

    if base_url is None:
        try:
            from app.core.config import get_settings

            base_url = get_settings().problem_base_url
        except Exception:  # noqa: BLE001
            base_url = "https://tem-platform.dev/problems"

    parsed_errors: list[ValidationErrorItem] | None = None
    if errors is not None:
        parsed_errors = [
            item
            if isinstance(item, ValidationErrorItem)
            else ValidationErrorItem(**item)
            for item in errors
        ]

    problem = ProblemDetails(
        type=f"{base_url.rstrip('/')}/{slug}",
        title=title,
        status=status_code,
        detail=detail,
        instance=instance,
        request_id=safe_req_id,
        errors=parsed_errors,
    )

    response_headers = dict(headers) if headers else {}
    response_headers["x-request-id"] = safe_req_id

    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(mode="json", exclude_none=True),
        media_type="application/problem+json",
        headers=response_headers,
    )


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
    # Mask 5xx internal errors to prevent information leakage (OWASP A05)
    detail = (
        "An unexpected server error occurred." if exc.status_code >= 500 else exc.detail
    )
    return create_problem_response(
        status_code=exc.status_code,
        title=exc.title,
        detail=detail,
        instance=request.url.path,
        slug=exc.slug,
        request_id=req_id,
        errors=exc.errors,
    )


async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    req_id = _get_request_id(request)
    formatted_errors = _format_validation_errors(exc.errors())
    return create_problem_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        title="Validation Error",
        detail="One or more fields failed validation.",
        instance=request.url.path,
        slug="validation-error",
        request_id=req_id,
        errors=formatted_errors,
    )


async def pydantic_validation_error_handler(
    request: Request, exc: PydanticValidationError
) -> JSONResponse:
    req_id = _get_request_id(request)
    formatted_errors = _format_validation_errors(exc.errors())
    return create_problem_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
    # Never leak internal 5xx details via Starlette HTTPException (OWASP A05)
    if exc.status_code >= 500:
        detail = "An unexpected server error occurred."
    else:
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


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    req_id = _get_request_id(request)
    logger.exception(
        "Unhandled exception processing request (path=%s, request_id=%s): %s",
        request.url.path,
        req_id,
        exc,
    )
    # Fail-safe: Always return generic safe message on 500 errors (OWASP A05)
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
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        PydanticValidationError, pydantic_validation_error_handler
    )  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        status.HTTP_500_INTERNAL_SERVER_ERROR, unhandled_exception_handler
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)
