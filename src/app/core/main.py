import logging

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine
from app.core.health import router as health_router
from app.core.logging import setup_logging

logger = logging.getLogger(__name__)


async def lifespan(app: FastAPI):
    # Perform any startup tasks here
    logger.info("Starting up the application...")
    get_engine()
    yield
    # Perform any shutdown tasks here
    await dispose_engine()
    logger.info("Shutting down the application...")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level.value)
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

    app.include_router(health_router)
    return app


app = create_app()
