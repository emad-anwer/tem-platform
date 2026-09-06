"""FastAPI authentication dependencies and principal resolution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.auth.context import set_current_principal
from app.core.auth.principal import Principal, Role
from app.core.auth.token_verifier import (
    TokenVerificationError,
    TokenVerifier,
    get_token_verifier,
)
from app.core.db import get_db
from app.core.repository import TenantRepository
import uuid
from app.core.config import get_settings

bearer_scheme = HTTPBearer(auto_error=False)


def get_verifier_factory() -> Callable[[], TokenVerifier]:
    """Provide lazy verifier construction so unauthenticated requests fail fast."""
    return get_token_verifier


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


_BOOTSTRAP_TENANT_ID = uuid.UUID(int=0)


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
    verifier_factory: Annotated[
        Callable[[], TokenVerifier], Depends(get_verifier_factory)
    ],
) -> Principal:
    """Verify credentials, resolve the tenant, and publish a Principal."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Authentication credentials are required.")

    settings = get_settings()
    if (
        settings.environment == "dev"
        and settings.bootstrap_admin_token
        and credentials.credentials == settings.bootstrap_admin_token
    ):
        principal = Principal(
            user_id="bootstrap-admin",
            tenant_id=_BOOTSTRAP_TENANT_ID,
            role=Role.PLATFORM_ADMIN,
        )
        set_current_principal(principal)
        return principal

    try:
        verifier = await run_in_threadpool(verifier_factory)
        claims = await run_in_threadpool(verifier.verify, credentials.credentials)
    except TokenVerificationError as exc:
        raise _unauthorized("Invalid authentication credentials.") from exc

    tenant = await TenantRepository(session).get_by_zitadel_org_id(
        claims.zitadel_org_id
    )
    if tenant is None or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated tenant is not available.",
        )

    principal = Principal(
        user_id=claims.user_id,
        tenant_id=tenant.id,
        role=claims.role,
    )
    set_current_principal(principal)
    return principal
