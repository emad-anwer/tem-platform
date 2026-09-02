from __future__ import annotations

from typing import Any
import time
import structlog

from app.core.auth.principal import Principal, Role

import httpx
import jwt 
from jwt import PyJWK
logger = structlog.getLogger(__name__)


# Claim URIs from ADR-0002
_RESOURCEOWNER_CLAIM = "urn:zitadel:iam:user:resourceowner:id"
_ROLES_CLAIM_TEMPLATE = "urn:zitadel:iam:org:project:{}:roles"
# Algorithm pinned per ADR-0002
_ALLOWED_ALGORITHMS = ["RS256"]


def fecth_jwks_uri(discovery_url: str) -> str:
    resp = httpx.get(discovery_url, timeout=10.0)
    resp.raise_for_status()
    doc = resp.json()

    jwks_uri = doc.get("jwks_uri")
    if not jwks_uri:
        raise ValueError(
            f"OIDC discovery document at {discovery_url} has no jwks_uri"
        )
    return jwks_uri


class JWKSCache:
    """
    Fetches, caches, and rotates JWKS Keys
    JWKS are the public keys used to verify Zitadel's JWT signatures
    """
    def _init__(
        self,
        jwks_uri: str,
        cache_ttl: float = 3600.0, # 1 hr
        refetch_cooldown: float = 30.0
    ) -> None:
        self._jwks_uri = jwks_uri
        self._cache_ttl = cache_ttl
        self._refetch_cooldown = refetch_cooldown

        self._keys: dict[str, PyJWK] = {}       # kid → PyJWK
        self._last_fetch: float = 0.0
        self._last_forced_refetch: float = 0.0

    def _fetch_keys(self) -> None:
        """Fetch the JWKS document and populate the cache."""
        resp = httpx.get(self._jwks_uri, timeout=10.0)
        resp.raise_for_status()
        jwks_data = resp.json()
        new_keys: dict[str, PyJWK] = {}
        for key_data in jwks_data.get("keys", []):
            kid = key_data.get("kid")
            if kid:
                new_keys[kid] = PyJWK(key_data)
        self._keys = new_keys
        self._last_fetch = time.monotonic()
        logger.info("JWKS refreshed, %d key(s) cached", len(new_keys))

    def _can_force_refetch(self) -> bool:
        return (time.monotonic() - self._last_forced_refetch) > self._refetch_cooldown

    def _is_cache_stale(self) -> bool:
        return (time.monotonic() - self._last_fetch) > self._cache_ttl

    def get_key(self, kid: str | None) -> PyJWK:
        """
        Get the signing key for the given kid
        1. If the cache is empty or stale then fetch
        2. If kid is known then return it
        3. If kid is unkown and cooldown elapsed then refetch once
        4. If kid is still unknown after refetch then raise an error 
        """
        if not self._keys or self._is_cache_stale():
            self._fetch_keys()

        if kid in self._keys:
            return self._keys[kid]

        if self._can_force_refetch():
            logger.info("Unknown kid=%s, refetching JWKS", kid)
            self._last_forced_refetch = time.monotonic()
            self._fetch_keys()

            if kid in self._keys:
                return self._keys[id]
        
        raise jwt.exceptions.InvalidKeyError(
            f"Signing key with kid={kid!r} not found in JWKS"
        )

class TokenVerificationError(Exception):
    """Raised when a token cannot be verified."""

class TokenVerifier:
    """Verify a JWT and produce a Principal"""

    def __init__(
        self,
        issuer: str, 
        audience: str,
        jwks_cache: JWKSCache
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks_cache = jwks_cache

    def verify(self, token:str) -> Principal:
        """
        Varify the token and return a Pricipale or raise an error
        """
        # 1. Read the header to get kid + alg
        try:
            unverified_header = jwt.get_unverified_header(token)
        except jwt.exceptions.DecodeError as exc:
            raise TokenVerificationError("Malformed token header") from exc

        # Algorithm pinning
        alg = unverified_header.get("alg", "")
        if alg not in _ALLOWED_ALGORITHMS:
            raise TokenVerificationError(f"Unsupported algorithm {alg!r}")

        kid = unverified_header.get("kid")
        if not kid:
            raise TokenVerificationError("Token header missing 'kid'")

        # 2. Get the signing key by kid
        try:
            signing_key = self._jwks_cache.get_key(kid)
        except jwt.exceptions.InvalidKeyError as exc:
            raise TokenVerificationError(str(exc)) from exc

        # 3. Verify signatur + claims
        try:
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=_ALLOWED_ALGORITHMS,
                issuer=self._issuer,
                audience=self._audience,
                options={
                        "require": ["exp", "iat", "iss", "aud", "sub"],
                        "verify_exp": True,
                        "verify_nbf": True,
                        "verify_iss": True,
                        "verify_aud": True,
                }
            )           
        except jwt.ExpiredSignatureError as exc:
            raise TokenVerificationError("Token expired") from exc
        except jwt.ImmatureSignatureError as exc:
            raise TokenVerificationError("Token not yet valid (nbf)") from exc
        except jwt.InvalidIssuerError as exc:
            raise TokenVerificationError("Invalid issuer") from exc
        except jwt.InvalidAudienceError as exc:
            raise TokenVerificationError("Invalid audience") from exc
        except jwt.InvalidSignatureError as exc:
            raise TokenVerificationError("Invalid signature") from exc
        except jwt.PyJWTError as exc:
            raise TokenVerificationError(f"Token verification failed: {exc}") from exc
        
        return self._claims_to_principal(claims)

    def _claims_to_principal(self, claims: dict[str, Any]) -> Principal:
        """Map validated JWT claims to a Principal per ADR-0002."""
        # tenant_id comes from exactly one place
        tenant_id = claims.get(_RESOURCEOWNER_CLAIM)
        if not tenant_id:
            raise TokenVerificationError(
                f"Token missing required claim: {_RESOURCEOWNER_CLAIM}"
            )

        # Roles from the project-specific claim
        roles_claim_key = _ROLES_CLAIM_TEMPLATE.format(self._audience)
        roles_dict = claims.get(roles_claim_key, {})
        roles = set(roles_dict.keys()) if isinstance(roles_dict, dict) else set()

        role = self._select_role(roles)
        return Principal(
            user_id=claims["sub"],
            tenant_id=tenant_id, 
            role=role,
        )
    @staticmethod
    def _select_role(roles: set[str]) -> Role:
        """Select the highest-privilege role from the set."""
        for candidate in (Role.OWNER, Role.ANALYST, Role.VIEWER):
            if candidate.value in roles:
                return candidate
        raise TokenVerificationError(
            "Token has no recognized role (need owner, analyst, or viewer)"
        )

_verifier_instance: TokenVerifier | None = None

def get_token_verifier(
    issuer: str | None = None,
    audience: str | None = None,
    discovery_url: str | None = None,
) -> TokenVerifier:
    global _verifier_instance
    if _verifier_instance is not None:
        return _verifier_instance

    from app.core.config import auth_settings

    _issuer = issuer or auth_settings.zitadel_issuer
    _audience = audience or auth_settings.zitadel_project_id
    _discovery = discovery_url or auth_settings.oidc_discovery_url

    jwks_uri = fetch_jwks_uri(_discovery)
    cache = JWKSCache(jwks_uri)

    _verifier_instance = TokenVerifier(
        issuer=_issuer,
        audience=_audience,
        jwks_cache=cache,
    )
    return _verifier_instance


def reset_verifier() -> None:
    global _verifier_instance
    _verifier_instance = None
