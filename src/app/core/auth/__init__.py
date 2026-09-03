"""Authentication and authorization primitives for the TEM platform.

Only this package may import JWT libraries or reference Zitadel-specific claims.
Everything outside core/auth/ receives only Principal and Role.
"""

from app.core.auth.principal import Principal, Role
from app.core.auth.token_verifier import (
    TokenVerificationError,
    TokenVerifier,
    VerifiedClaims,
    get_token_verifier,
)

__all__ = [
    "Principal",
    "Role",
    "TokenVerificationError",
    "TokenVerifier",
    "VerifiedClaims",
    "get_token_verifier",
]
