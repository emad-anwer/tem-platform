from __future__ import annotations

from typing import Any
import time
import structlog

from app.core.auth.principal import Principal, Role
from jwt import PyJWKClient

logger = structlog.getLogger(__name__)


# Claim URIs from ADR-0002
_RESOURCEOWNER_CLAIM = "urn:zitadel:iam:user:resourceowner:id"
_ROLES_CLAIM_TEMPLATE = "urn:zitadel:iam:org:project:{}:roles"
# Algorithm pinned per ADR-0002
_ALLOWED_ALGORITHMS = ["RS256"]


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

    def _fetch_keys():
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


        
        