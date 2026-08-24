from fastapi import FastAPI
from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine
from app.core.health import router as health_router


async def lifespan(app: FastAPI):
    # Perform any startup tasks here
    print("Starting up the application...")
    get_engine()
    yield
    # Perform any shutdown tasks here
    await dispose_engine()
    print("Shutting down the application...")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

    app.include_router(health_router)
    return app


app = create_app()
