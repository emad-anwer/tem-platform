from sqlite3 import IntegrityError

from uuid import UUID
from fastapi import Depends
from pydantic import ValidationError
import structlog

from app.core.auth.dependencies import get_principal
from app.core.auth.principal import Principal, Role
from app.core.db import get_db
from app.core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.core.jobs.states import ScanRunStatus
from app.core.pipeline.validation import TargetKind, normalize_target
from app.core.redis import get_arq_pool
from app.core.repository import TargetRepository, ScanRunRepository, FindingRepository
from app.core.models import Finding, ScanRun, Target
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)
DEFAULT_SCAN_MAX_ATTEMPTS = 3


try:
    from app.core.jobs.scan import SCAN_JOB_NAME, ScanJobPayload  # type: ignore[import]
except ImportError:
    from pydantic import BaseModel as _BaseModel

    SCAN_JOB_NAME = "run_scan"

    class ScanJobPayload(_BaseModel):  # type: ignore[no-redef]
        tenant_id: UUID
        target_id: UUID
        scan_run_id: UUID


async def get_pipeline_service(
    session: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> "PipelineService":
    return PipelineService(session, principal)


class PipelineService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self._session = session
        self._principal = principal
        self._targets = TargetRepository(session)
        self._scan_runs = ScanRunRepository(session)
        self._findings = FindingRepository(session)

    def _require_writer(self) -> None:
        if self._principal.role == Role.VIEWER:
            raise ForbiddenError(
                detail="Viewers do not have write access to this resource."
            )

    # ----------------Targets---------------
    async def create_target(self, *, kind: TargetKind, value: str) -> Target:
        self._require_writer()

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
        self._require_writer()
        target = await self.get_target_or_404(target_id)
        if not target.is_active:
            raise ValidationError(
                detail="Cannot start a scan for an inactive target.",
                errors=[{"field": "target_id", "message": "Target is inactive."}],
            )

        scan_run = await self._scan_runs.create(
            target_id=target.id,
            status=ScanRunStatus.QUEUED.value,
            max_attempts=DEFAULT_SCAN_MAX_ATTEMPTS,
        )

        payload = ScanJobPayload(
            target_id=target.id,
            scan_run_id=scan_run.id,
        )

        try:
            pool = await get_arq_pool()
            job = await pool.enqueue_job(
                SCAN_JOB_NAME, payload, _job_id=str(scan_run.id)
            )
        except Exception as exc:
            logger.warning(
                "pipeline.scan_enqueue_failed",
                scan_run_id=str(scan_run.id),
                target_id=str(target.id),
                error=str(exc),
            )
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
            scan_run = await self._scan_runs.update(scan_run.id, arq_job_id=job.job_id)
            scan_run.arq_job_id = job.job_id

        return scan_run

    async def get_scan_run_or_404(self, scan_run_id: UUID) -> ScanRun:
        scan_run = await self._scan_runs.get_by_id(scan_run_id)
        if scan_run is None:
            raise NotFoundError(detail=f"Scan run '{scan_run_id}' not found.")
        return scan_run

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
                scan_run_id=scan_run_id,
            )
        except ValueError as exc:
            raise BadRequestError(detail="Invalid cursor.") from exc
