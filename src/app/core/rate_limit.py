"""Shared, Redis-backed rolling-window limits for outbound scanner traffic.

The sorted set is deliberately a *sliding* window, rather than a fixed
counter: a fixed counter can admit twice the configured rate around a second
boundary.  Redis runs the Lua script serially, so pruning, counting and adding
an operation are one decision even when several workers make it concurrently.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.redis import get_redis

_WINDOW_MS = 1_000

# Redis TIME supplies one clock for all workers.  A member nonce matters when
# several admissions occur in the same millisecond: ZADD would otherwise
# overwrite one event and under-count the shared budget.
_CHECK_SLIDING_WINDOW = """
local time = redis.call('TIME')
local now = time[1] * 1000 + math.floor(time[2] / 1000)
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count < limit then
  redis.call('ZADD', KEYS[1], now, tostring(now) .. ':' .. ARGV[3])
  redis.call('PEXPIRE', KEYS[1], window * 2)
  return {1, 0}
end
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')[2]
return {0, math.max(1, tonumber(oldest) + window - now)}
"""


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    wait_seconds: float = 0.0


class RateLimitWaitCapped(RuntimeError):
    """The next shared-budget slot is farther away than the caller permits."""


class SlidingWindowRateLimiter:
    """Per-host limits shared by every process connected to this Redis."""

    def __init__(
        self,
        redis: Any | None = None,
        *,
        default_per_second: int = 5,
        overrides: Mapping[str, int] | None = None,
        maximum_wait_seconds: float = 10.0,
        redis_factory: Callable[[], Awaitable[Any | None]] = get_redis,
    ) -> None:
        if default_per_second <= 0:
            raise ValueError("default_per_second must be greater than zero")
        if maximum_wait_seconds < 0:
            raise ValueError("maximum_wait_seconds must not be negative")
        self._redis = redis
        self._redis_factory = redis_factory
        self._default = default_per_second
        self._overrides = {
            key.lower().rstrip("."): value for key, value in (overrides or {}).items()
        }
        if any(value <= 0 for value in self._overrides.values()):
            raise ValueError("rate-limit overrides must be greater than zero")
        self.maximum_wait_seconds = maximum_wait_seconds

    def limit_for(self, host: str, operation: str = "network") -> int:
        """Use ``operation:host`` first, then a host override, then default."""
        normalized = host.lower().rstrip(".")
        return self._overrides.get(
            f"{operation.lower()}:{normalized}",
            self._overrides.get(normalized, self._default),
        )

    def _key(self, host: str, operation: str) -> str:
        # Do not put user-controlled host strings directly into Redis keys.
        identity = f"{operation.lower()}:{host.lower().rstrip('.')}".encode()
        return f"scan-rate-limit:{hashlib.sha256(identity).hexdigest()}"

    async def check(
        self, host: str, *, operation: str = "network"
    ) -> RateLimitDecision:
        """Atomically admit now or report when the oldest event expires."""
        redis = self._redis if self._redis is not None else await self._redis_factory()
        if redis is None:
            raise RuntimeError("Redis is required before opening scanner connections")
        limit = self.limit_for(host, operation)
        result = await redis.eval(
            _CHECK_SLIDING_WINDOW,
            1,
            self._key(host, operation),
            limit,
            _WINDOW_MS,
            secrets.token_hex(12),
        )
        allowed, wait_ms = (int(value) for value in result)
        return RateLimitDecision(bool(allowed), wait_ms / 1_000)

    async def wait_for_permission(
        self,
        host: str,
        *,
        operation: str = "network",
        maximum_wait_seconds: float | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        can_wait: Callable[[float], bool] | None = None,
    ) -> None:
        """Wait and retry; a wait is never treated as a reservation."""
        cap = (
            self.maximum_wait_seconds
            if maximum_wait_seconds is None
            else maximum_wait_seconds
        )
        if cap < 0:
            raise ValueError("maximum_wait_seconds must not be negative")
        while True:
            decision = await self.check(host, operation=operation)
            if decision.allowed:
                return
            if decision.wait_seconds > cap or (
                can_wait and not can_wait(decision.wait_seconds)
            ):
                raise RateLimitWaitCapped(
                    "shared rate-limit wait "
                    f"({decision.wait_seconds:.3f}s) exceeds execution budget"
                )
            await sleep(decision.wait_seconds)


def configured_rate_limiter() -> SlidingWindowRateLimiter:
    """Build a limiter from the current settings (easy to inject in tests)."""
    settings = get_settings()
    return SlidingWindowRateLimiter(
        default_per_second=settings.scan_rate_limit_default_per_second,
        overrides=settings.scan_rate_limit_overrides,
        maximum_wait_seconds=settings.scan_rate_limit_max_wait_seconds,
    )
