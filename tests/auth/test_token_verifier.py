from __future__ import annotations

import pytest
import time
from auth_fixtures import FIXTURE_ISSUER, FIXTURE_PROJECT_ID, make_token
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.auth.principal import Role
from app.core.auth.token_verifier import TokenVerificationError


def test_valid_token_returns_principal(rsa_private_key, test_verifier):
    """A valid token with all required claims produces a correct Principal."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-test-123",
        role="analyst",
        user_id="user-abc",
    )
    principal = test_verifier.verify(token)

    assert principal.user_id == "user-abc"
    assert principal.tenant_id == "org-test-123"
    assert principal.role == Role.ANALYST


def test_expired_token_rejected(rsa_private_key, test_verifier):
    """An expired token raises TokenVerificationError."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-1",
        exp_offset=-60,  # expired 60 seconds ago
    )
    with pytest.raises(TokenVerificationError, match="expired"):
        test_verifier.verify(token)


def test_not_yet_valid_token_rejected(rsa_private_key, test_verifier):
    """A token with nbf in the future raises TokenVerificationError."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-1",
        nbf_offset=300,  # not valid for 5 more minutes
    )
    with pytest.raises(TokenVerificationError, match="not yet valid"):
        test_verifier.verify(token)


def test_wrong_issuer_rejected(rsa_private_key, test_verifier):
    """A token from a different issuer raises TokenVerificationError."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-1",
        issuer="https://evil.idp.com",
    )
    with pytest.raises(TokenVerificationError, match="[Ii]ssuer"):
        test_verifier.verify(token)


def test_wrong_audience_rejected(rsa_private_key, test_verifier):
    """A token for a different application raises TokenVerificationError."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-1",
        audience="wrong-project-id",
    )
    with pytest.raises(TokenVerificationError, match="[Aa]udience"):
        test_verifier.verify(token)


def test_unknown_kid_rejected(rsa_private_key, test_verifier):
    """A token with a kid not in our JWKS raises TokenVerificationError."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-1",
        kid="unknown-key-999",
    )
    with pytest.raises(TokenVerificationError, match="kid"):
        test_verifier.verify(token)


def test_alg_none_rejected(test_verifier):
    """A token with alg: none is rejected — algorithm confusion attack."""
    token = make_token(
        private_key=None,
        tenant_zitadel_org_id="org-1",
        algorithm="none",
    )
    with pytest.raises(TokenVerificationError, match="[Aa]lgorithm"):
        test_verifier.verify(token)


def test_wrong_signing_key_rejected(fixture_jwks, test_verifier):
    """A token signed with a different RSA key fails signature check."""
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(
        private_key=other_key,
        tenant_zitadel_org_id="org-1",
    )
    with pytest.raises(TokenVerificationError, match="[Ss]ignature"):
        test_verifier.verify(token)


def test_missing_tenant_id_rejected(rsa_private_key, test_verifier):
    """A valid token without the resourceowner claim is rejected."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-1",
        **{"urn:zitadel:iam:user:resourceowner:id": None},  # remove claim
    )
    with pytest.raises(TokenVerificationError, match="resourceowner"):
        test_verifier.verify(token)
