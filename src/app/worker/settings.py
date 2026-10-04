"""arq worker configuration and lifecycle hooks."""

from typing import Any, ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy.exc import SQLAlchemyError

from app.core import discovery  # noqa: F401, register discovery jobs
from app.core.auth.job_context import JOB_REGISTRY
from app.core.config import get_settings
from app.core.db import dispose_engine, wait_for_db
from app.core.jobs import scan  # noqa: F401, register scan jobs
from app.core.jobs.schedule import enqueue_scheduled_scans, sweep_stale_runs
from app.core.logging import setup_logging
from app.core.redis import (
    build_arq_redis_settings,
    dispose_redis,
    get_redis,
    wait_for_redis,
)
from app.core.scope import get_scope

logger = structlog.get_logger(__name__)


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

    # W4-02: a malformed scan scope entry stops the worker before it can
    # accept a job, rather than refusing (or worse, mis-scoping) at runtime.
    scope = get_scope()
    logger.info("scan.scope_loaded", entries=len(scope.entries))

    ctx["settings"] = settings
    logger.info("worker.ready")


async def shutdown(ctx: dict) -> None:
    """Close worker connections after active jobs drain."""
    logger.info("worker.shutting_down")
    await dispose_redis()
    await dispose_engine()
    logger.info("worker.stopped")


def _cron_minute_set(interval_minutes: int) -> set[int]:
    """Every-N-minutes within the hour (e.g. 5 → {0, 5, …, 55})."""
    return {minute for minute in range(60) if minute % interval_minutes == 0}


def _cron_schedule(interval_minutes: int) -> dict[str, Any]:
    """Map a minute interval onto arq cron's hour/minute sets.

    Sub-hour intervals run at those minutes past every hour. Hour-plus
    intervals round down to whole hours (90 minutes runs hourly) — arq cron
    has no finer grain above the hour, and an explicit setting would pretend
    otherwise.
    """
    if interval_minutes < 60:
        return {"minute": _cron_minute_set(interval_minutes)}
    hour_step = interval_minutes // 60
    return {
        "minute": {0},
        "hour": {hour for hour in range(24) if hour % hour_step == 0},
    }


class WorkerSettings:
    """Settings consumed by arq."""

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------

    redis_settings: RedisSettings = build_arq_redis_settings(get_settings())

    # ------------------------------------------------------------------
    # Job registry
    #
    # Add coroutine job functions here as modules implement them.
    # ------------------------------------------------------------------

    functions: ClassVar[list] = list(JOB_REGISTRY.values()) + [
        sweep_stale_runs,
        enqueue_scheduled_scans,
    ]

    # ------------------------------------------------------------------
    # Cron (W4-09, issue #101) — the platform doing things nobody asked for.
    #
    # run_at_startup is True for the sweeper, False for scans. The sweeper
    # is idempotent, so extra runs after deploy restarts are harmless — and
    # a restart is exactly when stale rows appear. Scans fan out across
    # tenants, so firing a full fan-out on every deploy would repeat a full
    # enqueue storm per restart; the next tick covers it instead.
    # unique=True (arq default) dedupes each tick across workers.
    # ------------------------------------------------------------------

    _schedule = get_settings()
    cron_jobs: ClassVar[list] = [
        cron(
            sweep_stale_runs,
            run_at_startup=True,
            **_cron_schedule(_schedule.scheduled_sweep_interval_minutes),
        ),
        cron(
            enqueue_scheduled_scans,
            run_at_startup=False,
            **_cron_schedule(_schedule.scheduled_scan_interval_minutes),
        ),
    ]
    del _schedule

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
