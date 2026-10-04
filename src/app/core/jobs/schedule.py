"""Scheduled platform work: the stale-run sweeper and recurring scans (W4-09).

Two arq cron jobs, no new dependencies:

- :func:`sweep_stale_runs` calls :func:`mark_stale_runs` every few minutes,
  closing the BUG-02 gap (tested function, zero callers).
- :func:`enqueue_scheduled_scans` enqueues one scan job per active target.

Decisions (the issue asks for them in writing):

- ``run_at_startup`` is True for the sweeper, False for scans. The sweeper
  is idempotent, so extra runs after deploy restarts are harmless — and a
  restart is exactly when stale rows appear. Scans fan out across tenants,
  so firing a full fan-out on every deploy (three Thursday deploys = three
  full enqueue storms) is the trap the issue names.
- A target whose latest run is still ``queued``/``running`` is **skipped**,
  not queued alongside. Concurrent duplicate scans of one target pile up
  worker load for no new information; the next tick picks it up.
- Both the interval and a per-tick cap bound the fan-out. The interval
  spreads load over time; the cap bounds a single tick (200 targets at once
  is a self-inflicted outage W4-05's per-host limiter cannot prevent).
- Overlap across workers is guarded by a best-effort Redis lock per tick,
  but correctness never depends on it: the sweeper is idempotent by
  construction, and scans are idempotent via skip-if-running plus arq's
  ``_job_id`` dedupe. A missed lock only repeats cheap, safe work.
- Tenant isolation mirrors ``tenant_job`` (W3-05's second caller, first one
  that loops): a system principal is set per target and reset in a
  ``finally``. Repositories read the context — never an explicit
  ``tenant_id=`` escape hatch — so forgetting the context fails loud via
  ``MissingTenantContextError`` instead of leaking rows.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.context import reset_current_principal, set_current_principal
from app.core.auth.job_context import system_principal
from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.discovery import SubdomainDiscoveryPayload, subdomain_discovery_job
from app.core.jobs.lifecycle import mark_stale_runs
from app.core.jobs.states import ScanRunStatus
from app.core.models import Target
from app.core.pipeline.service import DEFAULT_SCAN_MAX_ATTEMPTS
from app.core.redis import get_arq_pool, get_redis
from app.core.repository import ScanRunRepository
from app.core.scope import check_scope

logger = structlog.get_logger(__name__)

_SWEEP_LOCK_KEY = "cron-lock:sweep-stale-runs"
_SCAN_LOCK_KEY = "cron-lock:enqueue-scheduled-scans"

# A target with a run in either of these states is skipped this tick.
_BUSY_RUN_STATUSES = {ScanRunStatus.QUEUED.value, ScanRunStatus.RUNNING.value}


async def _acquire_tick_lock(*, key: str, ttl_seconds: int) -> bool:
    """Best-effort per-tick overlap guard. True means "we own this tick"."""
    try:
        redis = await get_redis()
    except Exception:  # noqa: BLE001 - lock is advisory; log and proceed.
        logger.warning("cron.lock_redis_unavailable", key=key)
        return True
    if redis is None:
        return True
    try:
        acquired = await redis.set(key, "1", nx=True, px=ttl_seconds * 1000)
    except Exception:  # noqa: BLE001 - see above.
        logger.warning("cron.lock_failed", key=key)
        return True
    if not acquired:
        logger.info("cron.tick_skipped_overlap", key=key)
    return bool(acquired)


def _lock_ttl_seconds(interval_minutes: int) -> int:
    """Lock lives almost a full interval — never into the next tick."""
    return max(30, interval_minutes * 60 - 30)


async def sweep_stale_runs_once(
    session: AsyncSession, *, job_timeout: float = 300.0
) -> int:
    """Mark worker-killed runs stale. Idempotent: a second call finds none."""
    marked = await mark_stale_runs(session, job_timeout=job_timeout)
    logger.info("cron.sweep_completed", marked=marked)
    return marked


async def sweep_stale_runs(ctx: dict[str, Any]) -> dict[str, Any]:
    """arq cron entry: reap runs stuck in ``running`` past twice the deadline."""
    settings = get_settings()
    if not await _acquire_tick_lock(
        key=_SWEEP_LOCK_KEY,
        ttl_seconds=_lock_ttl_seconds(settings.scheduled_sweep_interval_minutes),
    ):
        return {"swept": 0, "skipped": "overlap"}
    async with get_session_factory()() as session:
        marked = await sweep_stale_runs_once(session)
    return {"swept": marked}


async def _schedule_one_target(
    session: AsyncSession,
    pool: Any,
    target: Target,
    *,
    scheduler_job_id: str,
) -> str:
    """Enqueue one scan for one target. Returns the outcome bucket name."""
    principal = system_principal(
        tenant_id=target.tenant_id,
        job_name="enqueue_scheduled_scans",
        job_id=scheduler_job_id,
    )
    principal_token = set_current_principal(principal)
    log_tokens = structlog.contextvars.bind_contextvars(
        tenant_id=str(target.tenant_id),
        target_id=str(target.id),
        job_name="enqueue_scheduled_scans",
    )
    try:
        return await _schedule_one_target_in_context(session, pool, target)
    finally:
        reset_current_principal(principal_token)
        structlog.contextvars.reset_contextvars(**log_tokens)


async def _schedule_one_target_in_context(
    session: AsyncSession, pool: Any, target: Target
) -> str:
    runs = ScanRunRepository(session)

    # Refused targets are never queued — same default-deny as start_scan.
    # Any scope/DNS failure skips the target; it must not abort the tick.
    # (CancelledError is BaseException, so worker shutdown still propagates.)
    try:
        await check_scope(target.value_normalized)
    except Exception:  # noqa: BLE001 - one bad target skips, the tick continues.
        logger.warning("cron.scheduled_scan_scope_skipped")
        return "skipped_scope"

    latest = await runs.get_latest_for_target(target.id)
    if latest is not None and latest.status in _BUSY_RUN_STATUSES:
        logger.info(
            "cron.scheduled_scan_skipped_busy", latest_status=str(latest.status)
        )
        return "skipped_running"

    run = await runs.create(target_id=target.id, max_attempts=DEFAULT_SCAN_MAX_ATTEMPTS)
    payload = SubdomainDiscoveryPayload(tenant_id=target.tenant_id, run_id=run.id)
    try:
        # Same job start_scan enqueues — NOT the run_scheduled_scan stub,
        # which is BUG-03/W4-10's to replace or delete. _job_id dedupes
        # against arq-level retries of the same run.
        job = await pool.enqueue_job(
            subdomain_discovery_job.__name__, payload, _job_id=str(run.id)
        )
    except Exception:  # noqa: BLE001 - enqueue failed; drop the row we made.
        logger.warning("cron.scheduled_scan_enqueue_failed")
        await runs.delete(run.id)
        return "failed"

    if job is not None:
        await runs.update(run.id, arq_job_id=job.job_id)
    logger.info("cron.scheduled_scan_enqueued")
    return "enqueued"


async def enqueue_scheduled_scans_once(
    session: AsyncSession,
    *,
    pool: Any | None = None,
    limit: int = 50,
    scheduler_job_id: str = "scheduler",
) -> dict[str, int]:
    """Enqueue one scan per active target. One bad target never aborts the tick.

    Targets are taken oldest-first up to ``limit``. Under persistent overload
    (more active targets than the cap every tick) the newest targets wait —
    a fair cursor is future work; the cap plus skip-if-running is this week's
    guardrail against a fan-out outage.
    """
    pool = pool if pool is not None else await get_arq_pool()
    stmt = (
        select(Target)
        .where(Target.is_active.is_(True))
        .order_by(Target.created_at.asc(), Target.id.asc())
        .limit(limit)
    )
    targets = list((await session.execute(stmt)).scalars().all())

    counts = {
        "enqueued": 0,
        "skipped_running": 0,
        "skipped_scope": 0,
        "failed": 0,
    }
    for target in targets:
        outcome = await _schedule_one_target(
            session, pool, target, scheduler_job_id=scheduler_job_id
        )
        counts[outcome] += 1

    logger.info("cron.scheduled_scans_completed", **counts)
    return counts


async def enqueue_scheduled_scans(ctx: dict[str, Any]) -> dict[str, Any]:
    """arq cron entry: re-scan every active target left alone by the API."""
    settings = get_settings()
    if not await _acquire_tick_lock(
        key=_SCAN_LOCK_KEY,
        ttl_seconds=_lock_ttl_seconds(settings.scheduled_scan_interval_minutes),
    ):
        return {"enqueued": 0, "skipped": "overlap"}
    async with get_session_factory()() as session:
        counts = await enqueue_scheduled_scans_once(
            session,
            limit=settings.scheduled_scan_max_targets_per_tick,
            scheduler_job_id=str(ctx.get("job_id", "scheduler")),
        )
    return counts
