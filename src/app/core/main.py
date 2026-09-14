import redis.exceptions
import structlog
from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth.context import PrincipalContextMiddleware
from app.core.config import get_settings
from app.core.db import dispose_engine, wait_for_db
from app.core.errors import register_error_handlers
from app.core.health import router as health_router
from app.core.logging import setup_logging
from app.core.middlewares.request_id import RequestIDMiddleware
from app.core.redis import dispose_redis, wait_for_redis
from app.core.routes import router as tenant_router
from app.core.zitadel.client import (
    ZitadelApiError,
    ZitadelUnavailableError,
    dispose_zitadel_client,
    wait_for_zitadel,
)
from app.core.pipeline.routes import router as pipeline_router

logger = structlog.get_logger(__name__)


async def lifespan(app: FastAPI):
    logger.info("Starting up the application...")
    try:
        await wait_for_db()
    except SQLAlchemyError:
        logger.warning(
            "Database startup check failed; continuing without a live DB connection."
        )
    try:
        await wait_for_redis()
    except redis.exceptions.RedisError:
        logger.warning(
            "Redis startup check failed; continuing without cache/queue support."
        )
    try:
        await wait_for_zitadel()
    except (ZitadelApiError, ZitadelUnavailableError):
        logger.warning(
            "Zitadel startup check failed; continuing without identity management support."
        )
    yield
    try:
        await dispose_redis()
    except redis.exceptions.RedisError:
        logger.warning("Redis shutdown failed gracefully.")
    try:
        await dispose_engine()
    except SQLAlchemyError:
        logger.warning("Database engine shutdown failed gracefully.")
    try:
        await dispose_zitadel_client()
    except (ZitadelApiError, ZitadelUnavailableError):
        logger.warning("Zitadel client shutdown failed gracefully.")
    logger.info("Shutting down the application...")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    # Middlewares
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(PrincipalContextMiddleware)

    # Register RFC 9457 exception handlers
    register_error_handlers(app)

    app.include_router(health_router)
    app.include_router(tenant_router)
    app.include_router(pipeline_router)
    return app


app = create_app()
