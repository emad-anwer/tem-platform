import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.db import dispose_engine, wait_for_db
from app.core.errors import (
    ConflictError,
    NotFoundError,
    ProblemDetailError,
    ValidationError,
    build_problem_details,
)
from app.core.health import router as health_router
from app.core.logging import setup_logging
from app.core.redis import dispose_redis, wait_for_redis
from app.core.routes import router as tenant_router

logger = logging.getLogger(__name__)


async def lifespan(app: FastAPI):
    logger.info("Starting up the application...")
    try:
        await wait_for_db()
    except Exception:
        logger.warning("Database startup check failed; continuing without a live DB connection.")
    try:
        await wait_for_redis()
    except Exception:
        logger.warning("Redis startup check failed; continuing without cache/queue support.")
    yield
    try:
        await dispose_redis()
    except Exception:
        logger.warning("Redis shutdown failed gracefully.")
    try:
        await dispose_engine()
    except Exception:
        logger.warning("Database engine shutdown failed gracefully.")
    logger.info("Shutting down the application...")


def _problem_response(
    request: Request,
    status_code: int,
    title: str,
    detail: str,
    problem_type: str,
    *,
    errors: list[dict[str, str]] | None = None,
) -> JSONResponse:
    payload = build_problem_details(
        request=request,
        status=status_code,
        title=title,
        detail=detail,
        problem_type=problem_type,
        errors=errors,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
    )


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

    @app.exception_handler(ProblemDetailError)
    async def problem_detail_handler(request: Request, exc: ProblemDetailError):
        return _problem_response(
            request,
            exc.status_code,
            exc.title,
            exc.detail,
            exc.problem_type,
            errors=exc.errors,
        )

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError):
        return _problem_response(
            request,
            exc.status_code,
            exc.title,
            exc.detail,
            exc.problem_type,
            errors=exc.errors,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        errors: list[dict[str, str]] = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            message = error.get("msg", "Invalid value")
            errors.append({"field": location or "request", "message": message})

        return _problem_response(
            request,
            422,
            "Validation Error",
            "One or more fields failed validation.",
            "validation-error",
            errors=errors,
        )

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError):
        return _problem_response(
            request,
            exc.status_code,
            exc.title,
            exc.detail,
            exc.problem_type,
            errors=exc.errors,
        )

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError):
        return _problem_response(
            request,
            exc.status_code,
            exc.title,
            exc.detail,
            exc.problem_type,
            errors=exc.errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return _problem_response(
                request,
                404,
                "Not Found",
                "The requested resource was not found.",
                "not-found",
            )
        if exc.status_code == 405:
            return _problem_response(
                request,
                405,
                "Method Not Allowed",
                "The requested method is not allowed for this resource.",
                "bad-request",
            )
        return _problem_response(
            request,
            exc.status_code,
            exc.__class__.__name__,
            str(exc.detail),
            "bad-request",
        )

    app.include_router(health_router)
    app.include_router(tenant_router)
    return app


app = create_app()
