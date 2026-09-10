"""arq WorkerSettings — the configuration object arq reads at startup.

Run with:
    python -m app.worker          (via __main__.py)
    arq app.worker.settings.WorkerSettings  (arq CLI)

Redis connection
----------------
arq needs its own ``RedisSettings`` object, but we must not open a second,
differently-configured pool.  The solution: derive arq's ``RedisSettings``
directly from the app ``Settings`` so both use the same host/port/password/db.
arq manages its own connection pool internally; this file just ensures it
points at the same server with the same credentials — no divergence possible.

Concurrency — READ THIS BEFORE WRITING W3-07
---------------------------------------------
arq runs all ``max_jobs`` concurrent jobs in **a single asyncio event loop**.
That means one synchronous blocking call stalls *every other in-flight job*:

    socket.getaddrinfo(...)   # stdlib DNS resolver — BLOCKING
    requests.get(...)         # requests library — BLOCKING
    time.sleep(1)             # BLOCKING

W3-07 resolves DNS for hundreds of hostnames per scan run.  If it calls the
stdlib resolver directly, the entire worker freezes for every lookup.

The fix is mandatory:
    # ✗ WRONG — blocks the event loop
    addrs = socket.getaddrinfo(hostname, 80)

    # ✓ CORRECT — offloads to a thread-pool executor
    loop = asyncio.get_running_loop()
    addrs = await loop.run_in_executor(None, socket.getaddrinfo, hostname, 80)

    # ✓ Also correct — use an async DNS library (aiodns, asyncio-resolver)
    result = await resolver.resolve(hostname)

This is not a style suggestion.  A synchronous DNS call inside an async job
that handles 100 hostnames will stall every other job on the loop for the
entire duration of those 100 serial system-call round trips.  The symptom is
not slowness: it is complete starvation of all other concurrent jobs until
the synchronous work finishes.

redis_required for the worker
------------------------------
``redis_required`` defaults to ``False`` in Settings because the API can run
without its optional cache. The worker makes a separate, explicit decision:
Redis is mandatory because the queue is the worker's entire input. Startup
therefore performs a successful ``PING`` after the shared Redis manager's
retry loop and exits if Redis is still unavailable.
"""

from typing import ClassVar

import structlog
from arq.connections import RedisSettings
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.core.db import dispose_engine, wait_for_db
from app.core.logging import setup_logging
from app.core.redis import dispose_redis, get_redis, wait_for_redis

logger = structlog.get_logger(__name__)


def _arq_redis_settings(settings: Settings) -> RedisSettings:
    """Build arq RedisSettings from the app Settings.

    Both the API pool (core/redis.py) and arq's pool point at the same Redis
    server with the same credentials — derived from the same source of truth.
    """
    url = settings.redis_url
    path = (url.path or "").lstrip("/")
    return RedisSettings(
        host=url.host or "localhost",
        port=url.port or 6379,
        password=url.password,
        database=int(path) if path else 0,
        conn_timeout=int(settings.redis_socket_connect_timeout),
        conn_retries=settings.redis_max_retries,
    )


async def startup(ctx: dict) -> None:
    """Called once when the worker process starts.

    Initialises logging, verifies Redis connectivity (fatal if unavailable),
    and warms up the database pool.  The ctx dict is shared across all jobs
    for the lifetime of the worker process.
    """
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
    """Called once when the worker process is stopping.

    Disposes connections cleanly so no sockets are left open after the process
    exits. arq stops claiming new jobs and waits for in-flight jobs before
    calling this hook, subject to ``job_completion_wait``.
    """
    logger.info("worker.shutting_down")
    await dispose_redis()
    await dispose_engine()
    logger.info("worker.stopped")


class WorkerSettings:
    """arq worker configuration.

    arq reads this class by convention: it looks for ``functions``,
    ``redis_settings``, ``on_startup``, ``on_shutdown``, etc. as class
    attributes.

    See: https://arq-docs.helpmanual.io/#arq.worker.Worker
    """

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------

    redis_settings: RedisSettings = _arq_redis_settings(get_settings())

    # ------------------------------------------------------------------
    # Job registry
    #
    # Register job functions here as modules implement them.  Each entry is
    # a coroutine function decorated with nothing special — arq picks them up
    # by reference.
    #
    # Example (add in W3-05+):
    #   from app.modules.asm.jobs import run_asm_scan
    #   functions = [run_asm_scan]
    # ------------------------------------------------------------------

    functions: ClassVar[list] = []

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    on_startup = startup
    on_shutdown = shutdown

    # ------------------------------------------------------------------
    # Concurrency and timeouts
    #
    # max_jobs=10: ten jobs share ONE event loop.  See the concurrency note
    # at the top of this file — blocking calls in any job stall all others.
    #
    # job_timeout=300: five minutes.  This matches compose.yaml's
    # stop_grace_period so a SIGTERM during the last second of a job still
    # gives it time to finish.  Override per-function with the @job decorator
    # or by passing timeout= to ctx["job_id"] enqueue calls.
    #
    # health_check_interval=30: arq writes a heartbeat key to Redis every 30 s
    # so external monitors can detect a stalled worker.
    # ------------------------------------------------------------------

    max_jobs: int = 10
    job_timeout: int = 300  # seconds
    job_completion_wait: int = 300  # seconds to drain after SIGTERM
    health_check_interval: int = 30  # seconds
