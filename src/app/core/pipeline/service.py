from fastapi import Depends

from app.core.auth.dependencies import get_principal
from app.core.auth.principal import Principal, Role
from app.core.db import get_db
from app.core.errors import ForbiddenError
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
    async def create_target(self, *, kind: str, value: str) -> Target:
        self._require_writer()
        return await self._targets.create(
            tenant_id=self._principal.tenant_id, kind=kind, value=value
        )
