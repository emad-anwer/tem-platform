"""Contract tests for the shared Redis sliding-window limiter."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

import pytest

from app.core.rate_limit import RateLimitWaitCapped, SlidingWindowRateLimiter


class FakeRedis:
    """Tiny atomic EVAL stand-in; records the admissions we measure below."""

    def __init__(self) -> None:
        self.now_ms = 0
        self.events: dict[str, list[int]] = defaultdict(list)
        self.admissions: dict[str, list[int]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def eval(self, _script, _keys, key, limit, window_ms, _nonce):
        async with self._lock:
            cutoff = self.now_ms - int(window_ms)
            self.events[key] = [stamp for stamp in self.events[key] if stamp > cutoff]
            if len(self.events[key]) < int(limit):
                self.events[key].append(self.now_ms)
                self.admissions[key].append(self.now_ms)
                return [1, 0]
            return [0, self.events[key][0] + int(window_ms) - self.now_ms]

    async def advance_sleep(self, seconds: float) -> None:
        self.now_ms += round(seconds * 1_000)


class TimeAdvancingFakeRedis(FakeRedis):
    """Fake Redis whose server clock progresses while callers actually wait."""

    def __init__(self) -> None:
        super().__init__()
        self._started_at = time.monotonic()

    async def eval(self, *args):
        self.now_ms = round((time.monotonic() - self._started_at) * 1_000)
        return await super().eval(*args)


def _limiter(redis: FakeRedis, **kwargs) -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(redis, default_per_second=5, **kwargs)


async def test_concurrent_callers_share_one_rolling_window() -> None:
    redis = FakeRedis()
    limiter = _limiter(redis)

    decisions = await asyncio.gather(
        *(limiter.check("lab-nginx", operation="tcp") for _ in range(20))
    )
    assert sum(decision.allowed for decision in decisions) == 5
    key = limiter._key("lab-nginx", "tcp")
    assert len(redis.events[key]) == 5
    # Measure every one-second window rather than relying on task ordering.
    assert all(
        sum(stamp <= event < stamp + 1_000 for event in redis.events[key]) <= 5
        for stamp in redis.events[key]
    )


async def test_twenty_callers_across_workers_take_one_shared_rate_horizon() -> None:
    """Exercise refill and waiting, not just the initial concurrent decision.

    Sliding windows allow the first five operations immediately. Therefore the
    last admission is about three seconds later, while the full four batches
    occupy a four-second rate horizon (last admission plus its one-second
    window).  This is the precise form of "20 at 5/s takes roughly 4s".
    """
    redis = TimeAdvancingFakeRedis()
    worker_one, worker_two = _limiter(redis), _limiter(redis)
    started_at = time.monotonic()

    await asyncio.wait_for(
        asyncio.gather(
            *(worker_one.wait_for_permission("lab-nginx") for _ in range(10)),
            *(worker_two.wait_for_permission("lab-nginx") for _ in range(10)),
        ),
        timeout=6,
    )

    elapsed = time.monotonic() - started_at
    key = worker_one._key("lab-nginx", "network")
    admissions = sorted(redis.admissions[key])
    assert len(admissions) == 20
    assert 2.8 <= elapsed < 5.0
    assert 3.7 <= (admissions[-1] - admissions[0]) / 1_000 + 1 < 5.0
    assert all(
        sum(stamp <= event < stamp + 1_000 for event in admissions) <= 5
        for stamp in admissions
    )


async def test_hosts_have_independent_budgets() -> None:
    redis = FakeRedis()
    limiter = _limiter(redis)

    decisions = await asyncio.gather(
        *(limiter.check("lab-nginx") for _ in range(5)),
        *(limiter.check("lab-apache") for _ in range(5)),
    )

    assert all(decision.allowed for decision in decisions)


async def test_two_limiter_instances_share_redis_budget() -> None:
    redis = FakeRedis()
    worker_one, worker_two = _limiter(redis), _limiter(redis)

    decisions = await asyncio.gather(
        *(worker_one.check("lab-nginx") for _ in range(3)),
        *(worker_two.check("lab-nginx") for _ in range(3)),
    )

    assert sum(decision.allowed for decision in decisions) == 5


async def test_wait_rechecks_then_proceeds() -> None:
    redis = FakeRedis()
    limiter = SlidingWindowRateLimiter(redis, default_per_second=1)
    await limiter.wait_for_permission("crt.sh", sleep=redis.advance_sleep)

    await limiter.wait_for_permission("crt.sh", sleep=redis.advance_sleep)

    assert redis.now_ms == 1_000


async def test_wait_cap_stops_before_sleeping() -> None:
    redis = FakeRedis()
    limiter = SlidingWindowRateLimiter(
        redis, default_per_second=1, maximum_wait_seconds=0.4
    )
    await limiter.wait_for_permission("crt.sh", sleep=redis.advance_sleep)

    with pytest.raises(RateLimitWaitCapped):
        await limiter.wait_for_permission("crt.sh", sleep=redis.advance_sleep)
    assert redis.now_ms == 0


def test_operation_override_beats_host_override() -> None:
    limiter = SlidingWindowRateLimiter(
        FakeRedis(),
        default_per_second=5,
        overrides={"crt.sh": 2, "http:crt.sh": 1},
    )
    assert limiter.limit_for("crt.sh", "http") == 1
    assert limiter.limit_for("crt.sh", "tcp") == 2
