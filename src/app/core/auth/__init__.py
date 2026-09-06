"""Authentication and authorization primitives for the TEM platform.

Only this package may import JWT libraries or reference Zitadel-specific claims.
Everything outside core/auth/ receives only Principal and Role.
"""

from app.core.auth.context import (
    clear_current_principal,
    get_current_principal,
    reset_current_principal,
    set_current_principal,
)
from app.core.auth.dependencies import get_principal
from app.core.auth.permissions import (
    PERMISSION_MATRIX,
    Permission,
    require_permission,
    require_role,
)
from app.core.auth.principal import Principal, Role
from app.core.auth.token_verifier import (
    TokenVerificationError,
    TokenVerifier,
    VerifiedClaims,
    get_token_verifier,
)

__all__ = [
    "PERMISSION_MATRIX",
    "Permission",
    "Principal",
    "Role",
    "TokenVerificationError",
    "TokenVerifier",
    "VerifiedClaims",
    "clear_current_principal",
    "get_current_principal",
    "get_principal",
    "get_token_verifier",
    "require_permission",
    "require_role",
    "reset_current_principal",
    "set_current_principal",
]
