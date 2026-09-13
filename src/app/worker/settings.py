"""arq worker configuration and lifecycle hooks."""

from typing import ClassVar

import structlog
from arq.connections import RedisSettings
from sqlalchemy.exc import SQLAlchemyError

from app.core import discovery  # noqa: F401, register discovery jobs
from app.core.auth.job_context import JOB_REGISTRY
from app.core.config import Settings, get_settings
from app.core.db import dispose_engine, wait_for_db
from app.core.jobs import scan  # noqa: F401, register scan jobs
from app.core.logging import setup_logging
from app.core.redis import dispose_redis, get_redis, wait_for_redis

logger = structlog.get_logger(__name__)


def _arq_redis_settings(settings: Settings) -> RedisSettings:
    """Build arq settings from the application Redis URL."""
    url = settings.redis_url
    path = (url.path or "").lstrip("/")
    if url.host is None or url.port is None:
        raise ValueError("REDIS_URL must include a host and port")
    return RedisSettings(
        host=url.host,
        port=url.port,
        password=url.password,
        database=int(path) if path else 0,  # Redis database 0 is the URL default.
        conn_timeout=int(settings.redis_socket_connect_timeout),
        conn_retries=settings.redis_max_retries,
    )


async def startup(ctx: dict) -> None:
    """Initialise logging and verify worker dependencies."""
    settings = get_settings()
    setup_logging(settings.log_level)

    logger.info("worker.starting", max_jobs=WorkerSettings.max_jobs)

    # Redis is non-negotiable for a worker: the queue *is* Redis. The shared
    # manager follows the API's optional-Redis policy, so perform an explicit
    # ping here and fail closed for the worker.
    try:
        await wait_for_redis()
        redis = await get_redis()
        if redis is None:
            raise RuntimeError(
                "Redis client unavailable after startup — check REDIS_URL and "
                "ensure the Redis service is reachable."
            )
        await redis.ping()
    except Exception:
        logger.exception(
            "worker.redis_unavailable",
            message=(
                "Worker cannot start without Redis.  "
                "Stopping now rather than running silently with no queue."
            ),
        )
        raise

    # Database pool — warn but don't crash; not every job needs DB access at
    # startup, and the pool connects lazily on first use.
    try:
        await wait_for_db()
    except SQLAlchemyError:
        logger.warning(
            "worker.db_unavailable",
            message="Database startup check failed; jobs that need DB will fail.",
        )

    ctx["settings"] = settings
    logger.info("worker.ready")


async def shutdown(ctx: dict) -> None:
    """Close worker connections after active jobs drain."""
    logger.info("worker.shutting_down")
    await dispose_redis()
    await dispose_engine()
    logger.info("worker.stopped")


class WorkerSettings:
    """Settings consumed by arq."""

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------

    redis_settings: RedisSettings = _arq_redis_settings(get_settings())

    # ------------------------------------------------------------------
    # Job registry
    #
    # Add coroutine job functions here as modules implement them.
    # ------------------------------------------------------------------

    functions: ClassVar[list] = list(JOB_REGISTRY.values())

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    on_startup = startup
    on_shutdown = shutdown

    # ------------------------------------------------------------------
    # Concurrency and timeouts
    #
    # All jobs share one event loop; blocking work stalls every job.
    # Compose uses the same 300-second shutdown window as job completion.
    # ------------------------------------------------------------------

    max_jobs: int = 10
    max_tries: int = 3
    job_timeout: int = 300  # seconds
    job_completion_wait: int = 300  # seconds to drain after SIGTERM
    health_check_interval: int = 30  # seconds
