from types import SimpleNamespace

import pytest

from app.worker import settings as worker_settings


class FakeRedis:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def ping(self) -> bool:
        if self.error is not None:
            raise self.error
        return True


@pytest.mark.asyncio
async def test_worker_startup_fails_when_redis_ping_fails(monkeypatch) -> None:
    settings = SimpleNamespace(log_level="INFO")

    monkeypatch.setattr(worker_settings, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_settings, "setup_logging", lambda level: None)
    monkeypatch.setattr(worker_settings, "wait_for_redis", lambda: None)
    monkeypatch.setattr(
        worker_settings,
        "get_redis",
        lambda: FakeRedis(ConnectionError("redis unavailable")),
    )

    async def wait_for_redis() -> None:
        return None

    async def get_redis() -> FakeRedis:
        return FakeRedis(ConnectionError("redis unavailable"))

    monkeypatch.setattr(worker_settings, "wait_for_redis", wait_for_redis)
    monkeypatch.setattr(worker_settings, "get_redis", get_redis)

    with pytest.raises(ConnectionError, match="redis unavailable"):
        await worker_settings.startup({})


@pytest.mark.asyncio
async def test_worker_startup_accepts_healthy_redis(monkeypatch) -> None:
    settings = SimpleNamespace(log_level="INFO")

    monkeypatch.setattr(worker_settings, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_settings, "setup_logging", lambda level: None)

    async def wait_for_redis() -> None:
        return None

    async def get_redis() -> FakeRedis:
        return FakeRedis()

    async def wait_for_db() -> None:
        return None

    monkeypatch.setattr(worker_settings, "wait_for_redis", wait_for_redis)
    monkeypatch.setattr(worker_settings, "get_redis", get_redis)
    monkeypatch.setattr(worker_settings, "wait_for_db", wait_for_db)

    context: dict = {}
    await worker_settings.startup(context)

    assert context["settings"] is settings


def test_worker_waits_for_jobs_before_shutdown() -> None:
    assert worker_settings.WorkerSettings.job_completion_wait == 300
    assert worker_settings.WorkerSettings.job_completion_wait == (
        worker_settings.WorkerSettings.job_timeout
    )
