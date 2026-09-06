from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import TenantProvisioningAttempt


class ProvisioningRepository:
    """Repository for managing tenant provisioning attempts."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def claim(self, idempotency_key: str) -> TenantProvisioningAttempt:
        """
        Atomically claim a key. Caller must catch IntegrityError to detect if the key was already claimed.
        """
        attempt = TenantProvisioningAttempt(idempotency_key=idempotency_key)
        self._session.add(attempt)
        await self._session.commit()
        return attempt

    async def get_locked_attempt(
        self, idempotency_key: str
    ) -> TenantProvisioningAttempt | None:
        """
        Get the attempt for the given key, if it exists. Returns None if not found.
        """
        result = await self._session.execute(
            select(TenantProvisioningAttempt)
            .where(TenantProvisioningAttempt.idempotency_key == idempotency_key)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def release(self, attempt: TenantProvisioningAttempt) -> None:
        """Zitadel was never reached (or rejected us), nothing was created,
        so the claim is safe to release for a clean retry."""
        await self._session.delete(attempt)
        await self._session.commit()
