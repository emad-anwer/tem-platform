from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings
from app.core.redis import RedisManager, build_arq_redis_settings


def test_build_arq_redis_settings_requires_host_and_port():
    fake_url = SimpleNamespace(host=None, port=None, password=None, path="")
    fake_settings = SimpleNamespace(
        redis_url=fake_url,
        redis_socket_connect_timeout=5,
        redis_max_retries=3,
    )

    with pytest.raises(ValueError, match="REDIS_URL must include a host and port"):
        build_arq_redis_settings(fake_settings)


def test_build_arq_redis_settings_translates_url_parts():
    fake_url = SimpleNamespace(
        host="redis.internal", port=6380, password="secret", path="/2"
    )
    fake_settings = SimpleNamespace(
        redis_url=fake_url,
        redis_socket_connect_timeout=5,
        redis_max_retries=3,
    )

    result = build_arq_redis_settings(fake_settings)

    assert result.host == "redis.internal"
    assert result.port == 6380
    assert result.password == "secret"
    assert result.database == 2


async def test_get_arq_pool_is_cached_across_calls(monkeypatch):
    import app.core.redis as redis_module

    manager = RedisManager(get_settings())
    fake_pool = AsyncMock()
    create_pool_mock = AsyncMock(return_value=fake_pool)
    monkeypatch.setattr(redis_module, "create_pool", create_pool_mock)

    first = await manager.get_arq_pool()
    second = await manager.get_arq_pool()

    assert first is fake_pool
    assert second is fake_pool
    create_pool_mock.assert_awaited_once()


async def test_get_arq_pool_never_touches_real_redis(monkeypatch):
    import app.core.redis as redis_module

    manager = RedisManager(get_settings())
    fake_pool = AsyncMock()
    monkeypatch.setattr(redis_module, "create_pool", AsyncMock(return_value=fake_pool))

    pool = await manager.get_arq_pool()
    await pool.enqueue_job("some_job", job_id="fake-1")

    fake_pool.enqueue_job.assert_awaited_once_with("some_job", job_id="fake-1")


async def test_dispose_redis_closes_and_clears_arq_pool(monkeypatch):
    import app.core.redis as redis_module

    manager = RedisManager(get_settings())
    fake_pool = AsyncMock()
    monkeypatch.setattr(redis_module, "create_pool", AsyncMock(return_value=fake_pool))
    await manager.get_arq_pool()

    await manager.dispose_redis()

    fake_pool.close.assert_awaited_once()

    monkeypatch.setattr(
        redis_module, "create_pool", AsyncMock(return_value=AsyncMock())
    )
    rebuilt = await manager.get_arq_pool()
    assert rebuilt is not fake_pool


async def test_reset_clears_arq_pool_reference():
    manager = RedisManager(get_settings())
    manager._arq_pool = AsyncMock()

    manager.reset()

    assert manager._arq_pool is None
