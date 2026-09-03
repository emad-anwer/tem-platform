from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.auth.context import (
    clear_current_principal,
    get_current_principal,
)
from app.core.auth.dependencies import get_principal
from app.core.auth.principal import Role
from app.core.auth.token_verifier import VerifiedClaims


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    def __init__(self, tenant):
        self._tenant = tenant

    async def execute(self, _statement):
        return FakeResult(self._tenant)


class FakeVerifier:
    def __init__(self, claims=None, error=None):
        self._claims = claims
        self._error = error

    def verify(self, _token):
        if self._error is not None:
            raise self._error
        return self._claims


@pytest.mark.asyncio
async def test_missing_credentials_returns_bearer_challenge():
    with pytest.raises(HTTPException) as error:
        await get_principal(None, FakeSession(None), FakeVerifier())

    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.asyncio
async def test_verified_claims_map_to_internal_principal_and_context():
    tenant_id = uuid4()
    tenant = SimpleNamespace(id=tenant_id, is_active=True)
    claims = VerifiedClaims(
        user_id="user-1",
        zitadel_org_id="org-1",
        role=Role.ANALYST,
    )

    principal = await get_principal(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"),
        FakeSession(tenant),
        FakeVerifier(claims=claims),
    )

    assert principal.user_id == "user-1"
    assert principal.tenant_id == tenant_id
    assert principal.role == Role.ANALYST
    assert get_current_principal() == principal

    clear_current_principal()


@pytest.mark.asyncio
async def test_inactive_tenant_is_forbidden():
    claims = VerifiedClaims("user-1", "org-1", Role.VIEWER)

    with pytest.raises(HTTPException) as error:
        await get_principal(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"),
            FakeSession(SimpleNamespace(id=uuid4(), is_active=False)),
            FakeVerifier(claims=claims),
        )

    assert error.value.status_code == 403
