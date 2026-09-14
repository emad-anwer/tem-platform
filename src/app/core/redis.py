import asyncio
import logging
import time

from redis.asyncio import Connection, ConnectionPool, Redis, SSLConnection
from redis.exceptions import RedisError
from arq import ArqRedis
from arq.connections import RedisSettings as ArqRedisSettings, create_pool

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Network-level failures that are not Redis protocol errors (e.g. DNS down, host
# unreachable, connection refused, timeout).  Caught alongside RedisError so that
# the health endpoint never raises on transport problems.
_TRANSPORT_ERRORS = (RedisError, OSError, asyncio.TimeoutError)


def _mask_url(url: object) -> str:
    """Return the URL with the password hidden, for safe logging.

    Rebuilt from parsed parts instead of ``str.replace()``: ``str(url)``
    returns the *percent-encoded* form while ``.password`` is *decoded*,
    so a password containing special characters (@ / : space ...) would
    never match and would be logged in full.

    Query params are intentionally omitted — none are used today; if one
    ever is (?ssl_cert_reqs=...), add explicit handling here.
    """
    host = getattr(url, "host", None) or ""
    port = getattr(url, "port", None)
    netloc = f"{host}:{port}" if port else host
    if getattr(url, "username", None):
        netloc = f"{url.username}:***@{netloc}"
    scheme = getattr(url, "scheme", None) or "redis"
    path = getattr(url, "path", None) or ""
    return f"{scheme}://{netloc}{path}"


def build_arq_redis_settings(settings: Settings) -> ArqRedisSettings:
    """Return a dict suitable for passing to ``arq.create_pool()``."""
    url = settings.redis_url
    path = (url.path or "").lstrip("/")
    if url.host is None or url.port is None:
        raise ValueError("REDIS_URL must include a host and port")
    return ArqRedisSettings(
        host=url.host,
        port=url.port,
        password=url.password,
        database=int(path) if path else 0,
        conn_timeout=int(settings.redis_socket_connect_timeout),
        conn_retries=settings.redis_max_retries,
    )


class RedisManager:
    """Manages a shared async Redis connection pool and client.

    Uses a factory pattern so the instance can be swapped in tests via
    ``create_redis_manager()`` without touching module-level state.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None
        self._pool_failed = False
        self._lock = asyncio.Lock()
        self._last_check: tuple[float, bool] | None = None

        self._arq_pool: ArqRedis | None = None
        self._arq_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lazy initialisation (lock-protected)
    # ------------------------------------------------------------------

    def _build_pool(self) -> ConnectionPool | None:
        """Parse the URL and build a ConnectionPool.  Returns None on failure."""
        try:
            url = self._settings.redis_url
            # redis-py 8.x has no `ssl` kwarg on Connection — TLS is selected
            # by choosing SSLConnection as the connection class (same thing
            # from_url() does internally for rediss:// URLs).
            connection_class = SSLConnection if url.scheme == "rediss" else Connection
            # "redis://host:6379/" leaves path == "/"; lstrip then treat the
            # empty remainder as db 0 instead of letting int("") raise.
            path = (url.path or "").lstrip("/")
            return ConnectionPool(
                connection_class=connection_class,
                host=url.host or "localhost",
                port=url.port or 6379,
                db=int(path) if path else 0,
                password=url.password,
                socket_connect_timeout=self._settings.redis_socket_connect_timeout,
                socket_timeout=self._settings.redis_socket_timeout,
                decode_responses=True,
                max_connections=20,
            )
        except (ValueError, RedisError) as exc:
            logger.error(
                "Failed to create Redis connection pool: %s  (url=%s)",
                exc,
                _mask_url(self._settings.redis_url),
            )
            return None

    async def get_redis(self) -> Redis | None:
        """Return the shared Redis client, creating it on first call."""
        if self._client is not None:
            return self._client
        async with self._lock:
            # Double-check after acquiring the lock.
            if self._client is not None:
                return self._client
            if self._pool is None:
                # A previous build failure is sticky: retrying on every call
                # would rebuild (and log) once per request. Reset happens in
                # dispose_redis()/reset().
                if self._pool_failed:
                    return None
                self._pool = self._build_pool()
                if self._pool is None:
                    self._pool_failed = True
                    return None
            self._client = Redis(connection_pool=self._pool)
            return self._client

    async def get_arq_pool(self) -> ArqRedis:
        """Return a cached arq pool for enqueuing jobs from the API"""
        if self._arq_pool is not None:
            return self._arq_pool
        async with self._arq_lock:
            if self._arq_pool is not None:
                return self._arq_pool
            settings = build_arq_redis_settings(self._settings)
            self._arq_pool = await create_pool(settings)
            return self._arq_pool

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def wait_for_redis(self) -> None:
        """Retry connecting until Redis responds or retries are exhausted.

        Exponential backoff: base_delay * 2^(attempt-1), capped at 30 s.
        If ``settings.redis_required`` is True, raises on final failure so
        that the process exits — use this in production when Redis is a hard
        dependency (arq, caching, rate-limiting all need it).

        A *pool construction* failure (bad URL/config) skips the retry loop
        entirely: retries cannot fix configuration, and looping would log
        misleading "retrying in Xs" messages while nothing is retried.
        """
        settings = self._settings

        def _final_failure() -> None:
            if settings.redis_required:
                raise RuntimeError(
                    f"Redis required but not available after "
                    f"{settings.redis_max_retries} attempts"
                ) from None
            logger.warning(
                "Redis not available after %d attempts, running without cache/queue",
                settings.redis_max_retries,
            )

        client = await self.get_redis()
        if client is None:
            # _pool_failed is sticky — this is a configuration error, not a
            # transient outage. Fail fast with an honest message.
            logger.error("Redis unavailable; skipping retries (see prior error)")
            _final_failure()
            return

        for attempt in range(1, settings.redis_max_retries + 1):
            try:
                await client.ping()
                logger.info(
                    "Redis connection established (url=%s)",
                    _mask_url(settings.redis_url),
                )
                return
            except _TRANSPORT_ERRORS:
                if attempt == settings.redis_max_retries:
                    _final_failure()
                    return
                delay = min(
                    settings.redis_retry_base_delay * (2 ** (attempt - 1)),
                    30,
                )
                logger.warning(
                    "Redis not ready (attempt %d/%d), retrying in %.1fs",
                    attempt,
                    settings.redis_max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # Health check (cached)
    # ------------------------------------------------------------------

    async def check_redis_connection(self) -> bool:
        """Ping Redis and cache the result for ``health_cache_ttl`` seconds."""
        now = time.monotonic()
        if (
            self._last_check is not None
            and now - self._last_check[0] < self._settings.redis_health_cache_ttl
        ):
            return self._last_check[1]

        try:
            client = await self.get_redis()
            if client is None:
                healthy = False
            else:
                await client.ping()
                healthy = True
        except _TRANSPORT_ERRORS:
            healthy = False

        self._last_check = (now, healthy)
        return healthy

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def dispose_redis(self) -> None:
        """Close client and pool.  Each step is isolated so a partial failure
        does not prevent the remaining cleanup.
        """
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                logger.debug("Error closing Redis client", exc_info=True)
            self._client = None

        if self._arq_pool is not None:
            try:
                await self._arq_pool.close()
            except Exception:
                logger.debug("Error closing arq Redis pool", exc_info=True)
            self._arq_pool = None

        if self._pool is not None:
            try:
                await self._pool.aclose()
            except Exception:
                logger.debug("Error closing Redis connection pool", exc_info=True)
            self._pool = None

        # Stale cached state must not outlive the connections: a cached
        # healthy=True after dispose would mask the outage until the TTL
        # expired, and a failed build is retryable on the next lifecycle.
        self._last_check = None
        self._pool_failed = False

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset internal state.  Use in tests to get a clean slate."""
        self._pool = None
        self._client = None
        self._last_check = None
        self._pool_failed = False
        self._arq_pool = None


# ======================================================================
# Module-level singleton (lazily created, lock-protected)
# ======================================================================

_manager: RedisManager | None = None
_manager_lock = asyncio.Lock()


async def _get_manager() -> RedisManager:
    """Return (or create) the module-level RedisManager."""
    global _manager
    if _manager is None:
        # Two coroutines hitting this before first init would otherwise each
        # build a manager; the loser's pool/client would leak un-disposed.
        async with _manager_lock:
            if _manager is None:
                _manager = RedisManager(get_settings())
    return _manager


def set_manager(manager: RedisManager) -> None:
    """Override the module-level manager.  Used in tests for DI."""
    global _manager
    _manager = manager


# Public API — health.py and main.py use these wrappers.
#
# NOTE: get_redis() is async and creates the client on first call —
# it MUST be awaited. There is deliberately no sync accessor: calling an
# async function without await silently returns a coroutine object whose
# truthiness is always True, which would only explode later at usage time.


async def get_redis() -> Redis | None:
    manager = await _get_manager()
    return await manager.get_redis()


async def wait_for_redis() -> None:
    await (await _get_manager()).wait_for_redis()


async def check_redis_connection() -> bool:
    return await (await _get_manager()).check_redis_connection()


async def dispose_redis() -> None:
    await (await _get_manager()).dispose_redis()


async def get_arq_pool() -> ArqRedis:
    manager = await _get_manager()
    return await manager.get_arq_pool()
