from sqlite3 import IntegrityError

from uuid import UUID
from fastapi import Depends
from pydantic import ValidationError

from app.core.auth.dependencies import get_principal
from app.core.auth.principal import Principal, Role
from app.core.db import get_db
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.pipeline.validation import TargetKind, normalize_target
from app.core.repository import TargetRepository, ScanRunRepository, FindingRepository
from app.core.models import Finding, ScanRun, Target
from sqlalchemy.ext.asyncio import AsyncSession


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
        target = await self._targets.get_by_id(
            target_id, tenant_id=self._principal.tenant_id
        )
        if target is None:
            raise NotFoundError(detail=f"Target '{target_id}' not found.")
        return target
