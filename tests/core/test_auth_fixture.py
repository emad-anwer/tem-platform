"""Tests for the in-process JWT test fixture infrastructure.

Validates that:
- The session RSA keypair and JWKS fixture are generated correctly
- make_token creates valid tokens matching ADR-0002 claim shapes
- make_token supports all required override scenarios (expired, not yet valid,
  wrong issuer, wrong audience, unknown kid, alg: none, signed with wrong key,
  missing resourceowner claim)
- auth_headers creates valid Authorization headers
- two_tenants fixture provisions two distinct tenants with zitadel_org_ids
- mock_jwks_endpoint intercepts JWKS requests via HTTP
"""

from __future__ import annotations

import httpx
import jwt
from auth_fixtures import (
    FIXTURE_ISSUER,
    FIXTURE_KID,
    FIXTURE_PROJECT_ID,
    make_token,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm


def test_rsa_keypair_and_jwks_fixture(rsa_private_key, fixture_jwks):
    """Fixture JWKS should contain the public half of the session RSA key."""
    assert isinstance(rsa_private_key, rsa.RSAPrivateKey)
    assert "keys" in fixture_jwks
    assert len(fixture_jwks["keys"]) == 1

    jwk = fixture_jwks["keys"][0]
    assert jwk["kid"] == FIXTURE_KID
    assert jwk["use"] == "sig"
    assert jwk["alg"] == "RS256"
    assert jwk["kty"] == "RSA"
    assert "n" in jwk
    assert "e" in jwk


def test_make_token_default_claims_shape(rsa_private_key, fixture_jwks):
    """make_token should mint a token matching ADR-0002 claim specifications."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-123",
        role="analyst",
        user_id="user-456",
    )

    public_key = RSAAlgorithm.from_jwk(fixture_jwks["keys"][0])
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=FIXTURE_PROJECT_ID,
        issuer=FIXTURE_ISSUER,
    )

    assert claims["iss"] == FIXTURE_ISSUER
    assert claims["aud"] == FIXTURE_PROJECT_ID
    assert claims["sub"] == "user-456"
    assert claims["urn:zitadel:iam:user:resourceowner:id"] == "org-123"
    assert claims[f"urn:zitadel:iam:org:project:{FIXTURE_PROJECT_ID}:roles"] == {
        "analyst": {}
    }
    assert "iat" in claims
    assert "exp" in claims
    assert claims["exp"] > claims["iat"]


def test_make_token_expired_override(rsa_private_key, fixture_jwks):
    """Overriding exp_offset to negative creates an expired token."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-123",
        exp_offset=-10,
    )

    public_key = RSAAlgorithm.from_jwk(fixture_jwks["keys"][0])
    try:
        jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=FIXTURE_PROJECT_ID,
            issuer=FIXTURE_ISSUER,
        )
        assert False, "Expected ExpiredSignatureError"
    except jwt.ExpiredSignatureError:
        pass


def test_make_token_not_yet_valid_override(rsa_private_key, fixture_jwks):
    """Setting nbf_offset in the future creates an immature token."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-123",
        nbf_offset=300,
    )

    public_key = RSAAlgorithm.from_jwk(fixture_jwks["keys"][0])
    try:
        jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=FIXTURE_PROJECT_ID,
            issuer=FIXTURE_ISSUER,
        )
        assert False, "Expected ImmatureSignatureError"
    except jwt.ImmatureSignatureError:
        pass


def test_make_token_wrong_issuer_override(rsa_private_key, fixture_jwks):
    """Overriding issuer creates a token that fails issuer validation."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-123",
        issuer="https://evil.idp.com",
    )

    public_key = RSAAlgorithm.from_jwk(fixture_jwks["keys"][0])
    try:
        jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=FIXTURE_PROJECT_ID,
            issuer=FIXTURE_ISSUER,
        )
        assert False, "Expected InvalidIssuerError"
    except jwt.InvalidIssuerError:
        pass


def test_make_token_wrong_audience_override(rsa_private_key, fixture_jwks):
    """Overriding audience creates a token that fails audience validation."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-123",
        audience="wrong-client-id",
    )

    public_key = RSAAlgorithm.from_jwk(fixture_jwks["keys"][0])
    try:
        jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=FIXTURE_PROJECT_ID,
            issuer=FIXTURE_ISSUER,
        )
        assert False, "Expected InvalidAudienceError"
    except jwt.InvalidAudienceError:
        pass


def test_make_token_unknown_kid(rsa_private_key):
    """Token with an unknown kid has that kid in its unverified headers."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-123",
        kid="unknown-key-999",
    )

    headers = jwt.get_unverified_header(token)
    assert headers["kid"] == "unknown-key-999"


def test_make_token_signed_with_wrong_key(fixture_jwks):
    """Token signed with a different key fails signature verification against fixture JWKS."""
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(
        private_key=other_key,
        tenant_zitadel_org_id="org-123",
    )

    public_key = RSAAlgorithm.from_jwk(fixture_jwks["keys"][0])
    try:
        jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=FIXTURE_PROJECT_ID,
            issuer=FIXTURE_ISSUER,
        )
        assert False, "Expected InvalidSignatureError"
    except jwt.InvalidSignatureError:
        pass


def test_make_token_alg_none():
    """Token with alg: none is encoded as an unsecured JWT."""
    token = make_token(
        private_key=None,
        tenant_zitadel_org_id="org-123",
        algorithm="none",
    )

    headers = jwt.get_unverified_header(token)
    assert headers["alg"].lower() == "none"


def test_make_token_remove_claim_with_none(rsa_private_key, fixture_jwks):
    """Passing None in overrides removes the claim entirely."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-123",
        **{"urn:zitadel:iam:user:resourceowner:id": None},
    )

    public_key = RSAAlgorithm.from_jwk(fixture_jwks["keys"][0])
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=FIXTURE_PROJECT_ID,
        issuer=FIXTURE_ISSUER,
    )
    assert "urn:zitadel:iam:user:resourceowner:id" not in claims


def test_auth_headers_fixture(auth_headers):
    """auth_headers fixture should format Authorization Bearer header."""
    headers = auth_headers("org-alpha", role="owner")
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Bearer ")


async def test_mock_jwks_endpoint_intercepts_http(fixture_jwks):
    """mock_jwks_endpoint in conftest intercepts HTTP requests to the JWKS endpoint."""
    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(f"{FIXTURE_ISSUER}/.well-known/jwks.json")

    assert response.status_code == 200
    assert response.json() == fixture_jwks


async def test_two_tenants_fixture_provisions_distinct_tenants(two_tenants):
    """two_tenants fixture provisions two distinct tenants with zitadel_org_id."""
    tenant_a, tenant_b = two_tenants
    assert tenant_a.id != tenant_b.id
    assert tenant_a.slug == "tenant-alpha"
    assert tenant_b.slug == "tenant-beta"
    assert tenant_a.zitadel_org_id == "zitadel-org-alpha-001"
    assert tenant_b.zitadel_org_id == "zitadel-org-beta-002"


def test_principal_and_role_primitives():
    """Principal should be frozen (immutable) and Role should have valid StrEnum values."""
    from dataclasses import FrozenInstanceError
    from uuid import uuid4

    import pytest

    from app.core.auth.principal import Principal, Role

    assert Role.OWNER == "owner"
    assert Role.ANALYST == "analyst"
    assert Role.VIEWER == "viewer"

    tenant_id = uuid4()
    principal = Principal(
        user_id="zitadel-user-1",
        tenant_id=tenant_id,
        role=Role.OWNER,
    )

    assert principal.user_id == "zitadel-user-1"
    assert principal.tenant_id == tenant_id
    assert principal.role == Role.OWNER

    with pytest.raises(FrozenInstanceError):
        principal.role = Role.ANALYST


async def test_tenant_repository_and_service_zitadel_org_id(db_session):
    """Repository and service should support zitadel_org_id lookup and creation."""
    from app.core.repository import TenantRepository
    from app.core.service import TenantService

    repo = TenantRepository(db_session)
    svc = TenantService(db_session)

    # Miss lookup
    missing = await repo.get_by_zitadel_org_id("non-existent-org")
    assert missing is None

    # Service creation with zitadel_org_id
    created = await svc.create_tenant(
        name="Org Test Corp",
        slug="org-test-corp",
        zitadel_org_id="zitadel-org-unique-999",
    )
    assert created.zitadel_org_id == "zitadel-org-unique-999"

    # Hit lookup
    found = await repo.get_by_zitadel_org_id("zitadel-org-unique-999")
    assert found is not None
    assert found.id == created.id
    assert found.name == "Org Test Corp"


def test_make_token_multiple_roles_and_tenant_id_override(
    rsa_private_key, fixture_jwks
):
    """make_token should support multiple roles list and tenant_id UUID input."""
    from uuid import uuid4

    tenant_uuid = uuid4()
    token = make_token(
        private_key=rsa_private_key,
        tenant_id=tenant_uuid,
        roles=["viewer", "analyst"],
        custom_claim="platform_val",
    )

    public_key = RSAAlgorithm.from_jwk(fixture_jwks["keys"][0])
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=FIXTURE_PROJECT_ID,
        issuer=FIXTURE_ISSUER,
    )

    assert claims["urn:zitadel:iam:user:resourceowner:id"] == str(tenant_uuid)
    roles_claim = claims[f"urn:zitadel:iam:org:project:{FIXTURE_PROJECT_ID}:roles"]
    assert "viewer" in roles_claim
    assert "analyst" in roles_claim
    assert claims["custom_claim"] == "platform_val"


def test_auth_headers_with_tenant_id_and_custom_overrides(auth_headers):
    """auth_headers should accept tenant_id and pass overrides through."""
    from uuid import uuid4

    tenant_uuid = uuid4()
    headers = auth_headers(
        tenant_id=tenant_uuid, role="viewer", custom_claim="header_val"
    )
    assert "Authorization" in headers
    token = headers["Authorization"].removeprefix("Bearer ")
    unverified = jwt.decode(token, options={"verify_signature": False})
    assert unverified["urn:zitadel:iam:user:resourceowner:id"] == str(tenant_uuid)
    assert unverified["custom_claim"] == "header_val"
