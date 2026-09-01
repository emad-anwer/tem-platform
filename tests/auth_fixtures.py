"""In-process JWT identity provider for the test suite.

No Zitadel. No network. Real RSA keys. Real token signing.
The real verify_token() code path runs; only the JWKS endpoint is substituted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

# ---------------------------------------------------------------------------
# Default fixtures constants
# ---------------------------------------------------------------------------

FIXTURE_ISSUER = "https://test.idp.local"
FIXTURE_PROJECT_ID = "test-project-000"
FIXTURE_KID = "test-key-1"

_RESOURCEOWNER_CLAIM = "urn:zitadel:iam:user:resourceowner:id"


# ---------------------------------------------------------------------------
# Session-scoped RSA keypair — generated once per test session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rsa_private_key():
    """Generate a 2048-bit RSA private key once for the entire test session."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def fixture_jwks(rsa_private_key) -> dict[str, Any]:
    """The public JWKS document served by the in-process IdP."""
    public_key = rsa_private_key.public_key()
    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk["kid"] = FIXTURE_KID
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return {"keys": [jwk]}


# ---------------------------------------------------------------------------
# Token factory
# ---------------------------------------------------------------------------


def make_token(
    *,
    private_key: Any,
    tenant_zitadel_org_id: str | None = None,
    tenant_id: str | uuid.UUID | None = None,
    role: str = "owner",
    roles: list[str] | None = None,
    user_id: str | None = None,
    issuer: str = FIXTURE_ISSUER,
    audience: str = FIXTURE_PROJECT_ID,
    kid: str | None = FIXTURE_KID,
    exp_offset: int = 900,
    nbf_offset: int | None = None,
    algorithm: str = "RS256",
    **overrides: Any,
) -> str:
    """Mint a signed JWT with the claim shape ADR-0002 specified.

    Use **overrides to inject or delete individual claims:
        make_token(..., issuer="wrong")
        make_token(..., audience="wrong")
        make_token(..., exp_offset=-10)
        make_token(..., **{"urn:zitadel:iam:user:resourceowner:id": None})
    """
    now = datetime.now(tz=UTC)
    org_id = tenant_zitadel_org_id or (str(tenant_id) if tenant_id else "test-org-1")

    roles_dict: dict[str, dict[str, Any]] = {}
    if roles is not None:
        for r in roles:
            roles_dict[r] = {}
    elif role:
        roles_dict[role] = {}

    claims: dict[str, Any] = {
        "iss": issuer,
        "sub": user_id or str(uuid.uuid4()),
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=exp_offset)).timestamp()),
        _RESOURCEOWNER_CLAIM: org_id,
        f"urn:zitadel:iam:org:project:{audience}:roles": roles_dict,
    }

    if nbf_offset is not None:
        claims["nbf"] = int((now + timedelta(seconds=nbf_offset)).timestamp())

    for k, v in overrides.items():
        if v is None:
            claims.pop(k, None)
        else:
            claims[k] = v

    headers: dict[str, Any] = {}
    if kid is not None:
        headers["kid"] = kid

    if algorithm.lower() == "none":
        return jwt.encode(
            claims,
            key="",
            algorithm="none",
            headers=headers if headers else None,
        )

    return jwt.encode(
        claims,
        private_key,
        algorithm=algorithm,
        headers=headers if headers else None,
    )


@pytest.fixture
def make_token_fn(rsa_private_key):
    """Fixture that returns the make_token factory bound to the session keypair."""

    def _factory(**kwargs: Any) -> str:
        return make_token(private_key=rsa_private_key, **kwargs)

    return _factory


@pytest.fixture
def auth_headers(make_token_fn):
    """Returns a helper that builds Authorization headers for a single call."""

    def _headers(
        tenant_zitadel_org_id: str | None = None,
        tenant_id: str | uuid.UUID | None = None,
        role: str = "owner",
        **overrides: Any,
    ) -> dict[str, str]:
        token = make_token_fn(
            tenant_zitadel_org_id=tenant_zitadel_org_id,
            tenant_id=tenant_id,
            role=role,
            **overrides,
        )
        return {"Authorization": f"Bearer {token}"}

    return _headers
