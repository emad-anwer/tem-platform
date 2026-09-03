"""FastAPI authentication dependencies and principal resolution."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.context import set_current_principal
from app.core.auth.principal import Principal
from app.core.auth.token_verifier import (
    TokenVerificationError,
    TokenVerifier,
    get_token_verifier,
)
from app.core.db import get_db
from app.core.repository import TenantRepository

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_principal(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> Principal:
    """Verify credentials, resolve the tenant, and publish a Principal."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Authentication credentials are required.")

    try:
        claims = verifier.verify(credentials.credentials)
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