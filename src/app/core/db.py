import time
import logging

from app.core.config import LogLevel, get_settings
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy import text

# Global variables to hold the database engine and session factory (lazy initialization)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_READYZ_CACHE_TTL_SECONDS = 5
_last_check: tuple[float, bool] | None = None

logger = logging.getLogger(__name__)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            str(settings.database_url),
            pool_pre_ping=True,
            echo=settings.log_level == LogLevel.DEBUG,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yields a database session for use in FastAPI endpoints."""
    async with get_session_factory()() as session:
        yield session


async def check_db_connection() -> bool:
    """Checks if the database connection can be established."""
    global _last_check
    now = time.monotonic()

    if _last_check is not None and now - _last_check[0] < _READYZ_CACHE_TTL_SECONDS:
        return _last_check[1]

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        healthy = True

    except Exception as e:
        logger.exception(f"Database connection check failed")
        healthy = False

    _last_check = (now, healthy)

    return healthy


async def dispose_engine() -> None:
    """Close pooled connection on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
