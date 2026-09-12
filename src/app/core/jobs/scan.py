from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import structlog

from app.core.auth.job_context import tenant_job

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class ScheduledScanPayload:
    tenant_id: uuid.UUID
    target_id: uuid.UUID


@tenant_job
async def run_scheduled_scan(
    ctx: dict[str, Any], payload: ScheduledScanPayload
) -> None:
    """Run a scheduled scan for the given tenant and target."""
    logger.info("scan.started", target_id=str(payload.target_id))
    # actual scan orchestration...
    logger.info("scan.completed", target_id=str(payload.target_id))
