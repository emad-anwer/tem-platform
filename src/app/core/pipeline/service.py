from collections.abc import Sequence
from uuid import UUID

import structlog
from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import get_principal
from app.core.auth.principal import Principal
from app.core.db import get_db
from app.core.errors import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.jobs.scan import ScanPayload, run_scheduled_scan
from app.core.jobs.states import ScanRunStatus
from app.core.models import Finding, ScanRun, ScanRunFinding, Target
from app.core.pipeline.validation import TargetKind, normalize_target
from app.core.redis import get_arq_pool
from app.core.repository import (
    FindingRepository,
    ScanRunFindingRepository,
    ScanRunRepository,
    TargetRepository,
)
from app.core.scope import check_scope

logger = structlog.get_logger(__name__)
DEFAULT_SCAN_MAX_ATTEMPTS = 3


def get_pipeline_service(
    session: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> "PipelineService":
    return PipelineService(session, principal)


class PipelineService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self._session = session
        self._principal = principal
        self._targets = TargetRepository(session, tenant_id=principal.tenant_id)
        self._scan_runs = ScanRunRepository(session, tenant_id=principal.tenant_id)
        self._findings = FindingRepository(session, tenant_id=principal.tenant_id)
        self._run_findings = ScanRunFindingRepository(
            session, tenant_id=principal.tenant_id
        )

    # ----------------Targets---------------
    async def create_target(self, *, kind: TargetKind, value: str) -> Target:

        try:
            value_normalized = normalize_target(kind, value)
        except ValueError as exc:
            raise ValidationError(
                detail="Target value failed validation.",
                errors=[{"field": "value", "message": str(exc)}],
            ) from exc

        try:
            return await self._targets.create(
                tenant_id=self._principal.tenant_id,
                kind=kind.value,
                value=value,
                value_normalized=value_normalized,
                is_active=True,
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError(
                detail="A target with this kind and value already exists for your tenant."
            ) from exc

    async def list_targets(
        self, *, size: int, cursor: str | None
    ) -> tuple[list[Target], str | None]:
        try:
            return await self._targets.list(limit=size, cursor=cursor)
        except ValueError as exc:
            raise ValidationError(
                detail="Invalid cursor value.",
                errors=[{"field": "cursor", "message": str(exc)}],
            ) from exc

    async def get_target_or_404(self, target_id: UUID) -> Target:
        target = await self._targets.get_by_id(target_id)
        if target is None:
            raise NotFoundError(detail=f"Target '{target_id}' not found.")
        return target

    # ------------------Scan Runs---------------
    async def start_scan(self, *, target_id: UUID) -> ScanRun:
        target = await self.get_target_or_404(target_id)
        if not target.is_active:
            raise ValidationError(
                detail="Cannot start a scan for an inactive target.",
                errors=[{"field": "target_id", "message": "Target is inactive."}],
            )

        # W4-02: default-deny scope, decided before a run row exists — a
        # refused target never gets queued, and the refusal is a 403.
        await check_scope(target.value_normalized)

        scan_run = await self._scan_runs.create(
            target_id=target.id,
            status=ScanRunStatus.QUEUED.value,
            max_attempts=DEFAULT_SCAN_MAX_ATTEMPTS,
        )

        payload = ScanPayload(
            tenant_id=self._principal.tenant_id,
            run_id=scan_run.id,
        )

        try:
            pool = await get_arq_pool()
            job = await pool.enqueue_job(
                run_scheduled_scan.__name__, payload, _job_id=str(scan_run.id)
            )
        except Exception as exc:
            logger.warning(
                "pipeline.scan_enqueue_failed",
                scan_run_id=str(scan_run.id),
                target_id=str(target.id),
                error=str(exc),
            )
            await self._scan_runs.delete(scan_run.id)
            raise ServiceUnavailableError(
                detail="Scan could not be scheduled right now. Please try again."
            ) from exc

        if job is not None:
            logger.info(
                "pipeline.scan_enqueued",
                scan_run_id=str(scan_run.id),
                target_id=str(target.id),
                job_id=job.job_id,
            )
            updated = await self._scan_runs.update(scan_run.id, arq_job_id=job.job_id)
            if updated is None:
                logger.warning(
                    "pipeline.scan_run_update_failed",
                    scan_run_id=str(scan_run.id),
                    target_id=str(target.id),
                )
                await self._scan_runs.delete(scan_run.id)
                raise ServiceUnavailableError(
                    detail="Scan could not be scheduled right now. Please try again."
                )
            scan_run = updated

        return scan_run

    async def get_scan_run_or_404(self, scan_run_id: UUID) -> ScanRun:
        scan_run = await self._scan_runs.get_by_id(scan_run_id)
        if scan_run is None:
            raise NotFoundError(detail=f"Scan run '{scan_run_id}' not found.")
        return scan_run

    async def get_scan_run_changes(
        self, *, scan_run_id: UUID, size: int, cursor: str | None
    ) -> tuple[Sequence[ScanRunFinding], dict[str, int], str | None]:
        scan_run = await self.get_scan_run_or_404(scan_run_id)
        if scan_run.status != ScanRunStatus.SUCCEEDED.value:
            raise ConflictError(
                detail="Changes are available only for successful scan runs."
            )
        try:
            return await self._run_findings.list_changes(
                scan_run_id=scan_run.id, limit=size, cursor=cursor
            )
        except ValueError as exc:
            raise ValidationError(
                detail="Invalid cursor value.",
                errors=[{"field": "cursor", "message": str(exc)}],
            ) from exc

    # ------------------Findings---------------
    async def list_findings(
        self,
        *,
        size: int,
        cursor: str | None,
        target_id: UUID | None,
        scan_run_id: UUID | None,
    ) -> tuple[list[Finding], str | None]:
        try:
            return await self._findings.list(
                limit=size,
                cursor=cursor,
                target_id=target_id,
                run_id=scan_run_id,
            )
        except ValueError as exc:
            raise ValidationError(
                detail="Invalid cursor value.",
                errors=[{"field": "cursor", "message": str(exc)}],
            ) from exc
