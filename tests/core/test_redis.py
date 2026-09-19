import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db"
)

import pytest
from pydantic import RedisDsn

from app.core.config import Settings
from app.core.redis import RedisManager, _mask_url


def make_manager(redis_url: str) -> RedisManager:
    return RedisManager(Settings(redis_url=RedisDsn(redis_url)))


def test_mask_url_hides_encoded_special_char_password() -> None:
    # str(RedisDsn) keeps the password percent-encoded while .password is
    # decoded; the masked URL must leak neither form.
    url = RedisDsn("redis://user:p%40ss%2Fw@redis:6379/0")
    masked = _mask_url(url)
    assert masked == "redis://user:***@redis:6379/0"
    assert "p@ss/w" not in masked
    assert "p%40ss%2Fw" not in masked


def test_build_pool_db_from_path_variants() -> None:
    assert make_manager("redis://h:6379/2")._build_pool().connection_kwargs["db"] == 2
    # Trailing slash without a number used to raise int("") -> ValueError.
    assert make_manager("redis://h:6379/")._build_pool().connection_kwargs["db"] == 0
    assert make_manager("redis://h:6379")._build_pool().connection_kwargs["db"] == 0


def test_build_pool_selects_connection_class_by_scheme() -> None:
    from redis.asyncio import Connection, SSLConnection

    plain = make_manager("redis://h:6379")._build_pool()
    tls = make_manager("rediss://h:6379")._build_pool()
    assert plain.connection_class is Connection
    assert tls.connection_class is SSLConnection


@pytest.mark.asyncio
async def test_pool_failure_is_sticky(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.redis as redis_module

    calls = 0

    def boom(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise ValueError("bad config")

    monkeypatch.setattr(redis_module, "ConnectionPool", boom)

    manager = make_manager("redis://h:6379")
    assert await manager.get_redis() is None
    assert await manager.get_redis() is None
    # Built exactly once; the sticky failure flag prevents per-call retries.
    assert calls == 1


@pytest.mark.asyncio
async def test_dispose_clears_cached_health_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        async def ping(self) -> None:
            return None

        async def aclose(self) -> None:
            return None

    manager = make_manager("redis://h:6379")
    manager._client = FakeClient()  # type: ignore[assignment]
    monkeypatch.setattr(manager, "_lock", __import__("asyncio").Lock())

    assert await manager.check_redis_connection() is True

    await manager.dispose_redis()

    assert manager._last_check is None
    assert manager._pool_failed is False


@pytest.mark.asyncio
async def test_wait_fails_fast_on_pool_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sticky pool failure must skip the retry loop — no fake 'retrying' sleeps."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    manager = make_manager("redis://h:6379")
    monkeypatch.setattr(type(manager), "_build_pool", lambda self: None)

    await manager.wait_for_redis()  # redis_required=False -> warn, no raise

    assert sleeps == []  # never slept: no retries happened


@pytest.mark.asyncio
async def test_wait_raises_when_required_and_pool_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = make_manager("redis://h:6379")
    manager._settings.redis_required = True
    monkeypatch.setattr(type(manager), "_build_pool", lambda self: None)

    with pytest.raises(RuntimeError):
        await manager.wait_for_redis()


def test_module_get_redis_is_coroutine_function() -> None:
    """Pin get_redis() as async so nobody silently reverts it to sync."""
    import inspect

    from app.core import redis as redis_pub

    assert inspect.iscoroutinefunction(redis_pub.get_redis)
