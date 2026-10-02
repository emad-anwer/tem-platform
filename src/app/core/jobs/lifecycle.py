import asyncio
import random
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from arq import Retry
from httpx import HTTPStatusError, TimeoutException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import ScanRun
from app.core.rate_limit import RateLimitWaitCapped
from app.core.repository import ScanRunRepository, fail_stale_scan_runs
from app.core.scope import ScopeViolationError

MAX_FAILURE_MESSAGE_LENGTH = 2000
RATE_LIMIT_DEADLINE_MARGIN_SECONDS = 1.0
_RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|token|password|secret|api[_-]?key|connection(?:string|_string))"
    r"\s*[:=]\s*[^\s,;]+"
)


class RetryableJobError(RuntimeError):
    """A failure that may succeed on a later attempt."""


class TerminalJobError(RuntimeError):
    """A failure that must not be retried."""


def classify_failure(error: BaseException) -> str:
    """Classify known transient failures without exposing their text."""
    if isinstance(error, RetryableJobError | TimeoutException | RateLimitWaitCapped):
        return "retryable"
    if isinstance(error, HTTPStatusError):
        return (
            "retryable"
            if error.response.status_code in _RETRYABLE_HTTP_STATUSES
            else "terminal"
        )
    return "terminal"


def scrub_failure_message(error: BaseException, *, error_kind: str) -> str:
    """Return a short reason without exception payloads or connection details."""
    if isinstance(error, asyncio.TimeoutError | TimeoutException):
        message = (
            "job deadline exceeded"
            if isinstance(error, asyncio.TimeoutError)
            else "outbound request timed out"
        )
    elif isinstance(error, HTTPStatusError):
        message = f"upstream HTTP {error.response.status_code}"
    elif isinstance(error, RetryableJobError):
        message = "retryable upstream failure"
    elif isinstance(error, TerminalJobError):
        message = "terminal job failure"
    elif isinstance(error, ScopeViolationError):
        # W4-02: no hostnames, addresses or entry text from the target out
        # through the stored message — the reason enum is enough, and the
        # structured scan.scope_refused log carries the detail.
        message = f"target outside scan scope ({error.reason.value})"
    else:
        message = "job failed"
    return f"{error_kind}: {message}"[:MAX_FAILURE_MESSAGE_LENGTH]


def full_jitter_delay(
    attempt: int,
    *,
    base_seconds: float = 1.0,
    cap_seconds: float = 30.0,
    random_value: Callable[[], float] = random.random,
) -> float:
    """Calculate exponential backoff with full jitter."""
    upper_bound = min(cap_seconds, base_seconds * (2 ** max(attempt - 1, 0)))
    return random_value() * upper_bound


async def execute_scan_run(
    ctx: dict[str, Any],
    work: Callable[[dict[str, Any], ScanRun], Awaitable[None]],
    *,
    max_attempts: int = 3,
    job_timeout: float = 300.0,
    random_value: Callable[[], float] = random.random,
) -> ScanRun | None:
    """Run one attempt while keeping Postgres authoritative for lifecycle."""
    db: AsyncSession = ctx["db"]
    run_id = UUID(str(ctx["run_id"]))
    job_id = str(ctx["job_id"])
    attempt = int(ctx.get("job_try", 1))
    repository = ScanRunRepository(db)

    run = await repository.claim_for_job(run_id, job_id=job_id)
    if run is None:
        return None

    try:
        async with asyncio.timeout(job_timeout):
            # Connection layers remain ARQ-agnostic.  Work supplies this
            # budget to them so they can defer before ARQ's hard timeout.
            ctx["scan_deadline_monotonic"] = (
                time.monotonic() + job_timeout - RATE_LIMIT_DEADLINE_MARGIN_SECONDS
            )
            await work(ctx, run)
    except Exception as error:  # noqa: BLE001 - lifecycle must persist every job failure.
        error_kind = classify_failure(error)
        message = scrub_failure_message(error, error_kind=error_kind)
        if error_kind == "retryable" and attempt < max_attempts:
            await repository.record_retry(
                run_id,
                attempt=attempt + 1,
                error_message=message,
            )
            raise Retry(
                defer=full_jitter_delay(attempt, random_value=random_value)
            ) from None
        await repository.fail(
            run_id,
            error_kind=error_kind,
            error_message=message,
            attempt=attempt,
        )
        return await repository.get_by_id(run_id)

    await repository.succeed(run_id)
    return await repository.get_by_id(run_id)


async def mark_stale_runs(
    session: AsyncSession,
    *,
    job_timeout: float = 300.0,
    now: datetime | None = None,
) -> int:
    """Mark running rows older than twice the job deadline as stale failures.

    Takes a bare session, not a tenant-scoped repository: the sweeper is a
    platform-level job with no tenant to scope to.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=job_timeout * 2)
    return await fail_stale_scan_runs(session, before=cutoff)
