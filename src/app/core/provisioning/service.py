from __future__ import annotations

import structlog
from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import ConflictError, LocalProvisioningFailedError
from app.core.models import ProvisioningStatus, Tenant, TenantProvisioningAttempt
from app.core.provisioning.repository import ProvisioningRepository
from app.core.repository import TenantRepository
from app.core.zitadel.client import (
    ZitadelApiError,
    ZitadelManagementClient,
    ZitadelUnavailableError,
    get_zitadel_client,
)
from app.core.provisioning.types import TenantProvisioningResult

logger = structlog.get_logger(__name__)


async def get_tenant_provisioning_service(
    session: AsyncSession = Depends(get_db),
    zitadel_client: ZitadelManagementClient = Depends(get_zitadel_client),
) -> "TenantProvisioningService":
    return TenantProvisioningService(session, zitadel_client)


class TenantProvisioningService:

    def __init__(self, session: AsyncSession, zitadel: ZitadelManagementClient) -> None:
        self._session = session
        self._tenants = TenantRepository(session)
        self._attempts = ProvisioningRepository(session)
        self._zitadel = zitadel

    async def provision_tenant(
        self, *, name: str, slug: str, idempotency_key: str
    ) -> TenantProvisioningResult:
        """
        Provision a new tenant. This is idempotent based on the idempotency_key.
        If the key has already been claimed, it will return the existing tenant.
        If the key has not been claimed, it will attempt to provision a new tenant.
        """
        attempt = TenantProvisioningAttempt(idempotency_key=idempotency_key)
        self._session.add(attempt)
        try:
            await self._session.commit()
        except IntegrityError:
            # The key has already been claimed, so we need to check if the attempt was successful or not.
            await self._session.rollback()
            return await self._resume(idempotency_key, name=name, slug=slug)

        try:
            org = await self._zitadel.create_organization(name=name)
        except (ZitadelUnavailableError, ZitadelApiError):
            logger.error(
                "zitadel_org_create_failed",
                idempotency_key=idempotency_key,
                tenant_name=name,
            )
            # Nothing was created, release the claim so a retry isn't
            # permanently stuck behind this failed attempt.
            await self._attempts.release(attempt)
            raise

        attempt.status = ProvisioningStatus.ORG_CREATED
        attempt.zitadel_org_id = org.org_id
        await self._session.commit()

        tenant = await self._finish_local_insert(
            attempt, name=name, slug=slug, org_id=org.org_id
        )
        return TenantProvisioningResult(tenant=tenant, created=True)

    async def _resume(
        self, idempotency_key: str, *, name: str, slug: str
    ) -> TenantProvisioningResult:
        """
        Resume a previously claimed provisioning attempt. This is called when the idempotency key has already been claimed.
        It will check if the attempt was successful or not, and return the existing tenant if it was successful.
        If the attempt failed, it will raise an error to indicate that the provisioning failed.
        """
        attempt = await self._attempts.get_locked_attempt(idempotency_key)
        if not attempt:
            await self._session.rollback()
            raise ConflictError(
                detail="Idempotency key state changed unexpectedly; retry."
            )

        if attempt.status == ProvisioningStatus.COMPLETED:
            await self._session.rollback()
            tenant = await self._tenants.get_by_id(attempt.tenant_id)
            return TenantProvisioningResult(tenant=tenant, created=False)

        if attempt.status == ProvisioningStatus.IN_PROGRESS:
            await self._session.rollback()
            raise ConflictError(
                detail="A request with this Idempotency-Key is already being processed."
            )

        # Org is created, resume by finishing the local insert
        tenant = await self._finish_local_insert(
            attempt, name=name, slug=slug, org_id=attempt.zitadel_org_id
        )
        return TenantProvisioningResult(tenant=tenant, created=False)

    async def _finish_local_insert(
        self, attempt: TenantProvisioningAttempt, *, name: str, slug: str, org_id: str
    ) -> Tenant:
        try:
            tenant = await self._tenants.create(
                name=name, slug=slug, zitadel_org_id=org_id
            )
        except IntegrityError:
            await self._session.rollback()

            winner = await self._tenants.get_by_zitadel_org_id(org_id)
            if winner:
                # Another request created the tenant first, so we can just return that one.
                attempt.status = ProvisioningStatus.COMPLETED
                attempt.tenant_id = winner.id
                await self._session.commit()
                return winner

            logger.error(
                "tenant_provisioning_local_insert_failed",
                idempotency_key=attempt.idempotency_key,
                zitadel_org_id=org_id,
                tenant_name=name,
            )

            raise LocalProvisioningFailedError(
                detail="Tenant provisioning failed after the identity organization was created."
            )

        attempt.status = ProvisioningStatus.COMPLETED
        attempt.tenant_id = tenant.id
        await self._session.commit()
        return tenant
