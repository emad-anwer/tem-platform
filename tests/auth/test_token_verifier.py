"""Tests for OIDC token verification — W2-04.

Each test targets a specific failure mode from the issue:
- expired token
- not yet valid (nbf in future)
- wrong issuer
- wrong audience
- unknown kid
- alg: none
- signed with a different key
- valid token missing tenant_id (resourceowner claim)

Plus: valid token → correct VerifiedClaims, key rotation success, and
cooldown rate-limiting.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from auth_fixtures import FIXTURE_ISSUER, FIXTURE_KID, FIXTURE_PROJECT_ID, make_token
from conftest import FakeJWKSCache
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from app.core.auth.principal import Role
from app.core.auth.token_verifier import TokenVerificationError, TokenVerifier


# ---- Happy path ----


def test_valid_token_returns_verified_claims(rsa_private_key, test_verifier):
    """A valid token with all required claims produces correct VerifiedClaims."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-test-123",
        role="analyst",
        user_id="user-abc",
    )
    result = test_verifier.verify(token)

    assert result.user_id == "user-abc"
    assert result.zitadel_org_id == "org-test-123"
    assert result.role == Role.ANALYST


# ---- Failure modes — each MUST fail if you delete the corresponding check ----


def test_expired_token_rejected(rsa_private_key, test_verifier):
    """An expired token raises TokenVerificationError."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-1",
        exp_offset=-60,
    )
    with pytest.raises(TokenVerificationError, match="expired"):
        test_verifier.verify(token)


def test_not_yet_valid_token_rejected(rsa_private_key, test_verifier):
    """A token with nbf in the future raises TokenVerificationError."""
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-1",
        nbf_offset=300,
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
        **{"urn:zitadel:iam:user:resourceowner:id": None},
    )
    with pytest.raises(TokenVerificationError, match="resourceowner"):
        test_verifier.verify(token)


# ---- Key rotation tests ----


def test_key_rotation_refetch_succeeds(rsa_private_key, fixture_jwks):
    """When a token uses a new kid, the cache refetches JWKS and finds it.

    This simulates key rotation: the IdP starts signing with a new key
    whose kid is unknown to the cache. The cache should refetch once and
    succeed if the new kid is now in the JWKS response.
    """
    new_kid = "rotated-key-2"

    # Build a JWKS response that includes BOTH the original and the new kid
    new_jwk = RSAAlgorithm.to_jwk(rsa_private_key.public_key(), as_dict=True)
    new_jwk["kid"] = new_kid
    new_jwk["use"] = "sig"
    new_jwk["alg"] = "RS256"

    updated_jwks = {"keys": fixture_jwks["keys"] + [new_jwk]}

    # Build a cache that starts with only the OLD key, but refetch returns both
    cache = FakeJWKSCache(fixture_jwks, jwks_uri=f"{FIXTURE_ISSUER}/oauth/v2/keys")

    # Override _fetch_keys to simulate the IdP returning the updated JWKS
    def _fake_fetch(self_cache=cache, new_data=updated_jwks):
        self_cache._keys = {}
        for kd in new_data["keys"]:
            kid = kd.get("kid")
            if kid:
                self_cache._keys[kid] = PyJWK(kd)
        self_cache._last_fetch = time.monotonic()

    # Patch only the _fetch_keys method on this instance
    cache._fetch_keys = _fake_fetch

    verifier = TokenVerifier(
        issuer=FIXTURE_ISSUER,
        audience=FIXTURE_PROJECT_ID,
        jwks_cache=cache,
    )

    # Mint a token with the rotated kid
    token = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-rotation",
        kid=new_kid,
    )

    # This should succeed — the cache refetches and finds the new kid
    result = verifier.verify(token)
    assert result.zitadel_org_id == "org-rotation"


def test_refetch_cooldown_limits_repeated_calls(rsa_private_key, fixture_jwks):
    """The refetch cooldown prevents an attacker from hammering the IdP.

    If we just refetched for an unknown kid, a second unknown kid within the
    cooldown window should be rejected immediately without a network call.
    """
    fetch_call_count = 0

    cache = FakeJWKSCache(
        fixture_jwks,
        jwks_uri=f"{FIXTURE_ISSUER}/oauth/v2/keys",
        refetch_cooldown=60.0,  # long cooldown
    )

    original_keys = dict(cache._keys)

    def _counting_fetch(self_cache=cache, orig=original_keys):
        nonlocal fetch_call_count
        fetch_call_count += 1
        self_cache._keys = dict(orig)
        self_cache._last_fetch = time.monotonic()

    cache._fetch_keys = _counting_fetch

    verifier = TokenVerifier(
        issuer=FIXTURE_ISSUER,
        audience=FIXTURE_PROJECT_ID,
        jwks_cache=cache,
    )

    # First unknown kid — triggers one refetch (which won't find it)
    token1 = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-1",
        kid="attacker-kid-1",
    )
    with pytest.raises(TokenVerificationError, match="kid"):
        verifier.verify(token1)

    first_fetch_count = fetch_call_count

    # Second unknown kid immediately after — should NOT trigger another refetch
    token2 = make_token(
        private_key=rsa_private_key,
        tenant_zitadel_org_id="org-1",
        kid="attacker-kid-2",
    )
    with pytest.raises(TokenVerificationError, match="kid"):
        verifier.verify(token2)

    # The refetch count should not have increased — cooldown blocked it
    assert fetch_call_count == first_fetch_count, (
        "Refetch was called again within the cooldown window — "
        "rate-limiting is not working"
    )
