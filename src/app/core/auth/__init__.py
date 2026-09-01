"""Authentication and authorization primitives for the TEM platform.

Only this package may import JWT libraries or reference Zitadel-specific claims.
Everything outside core/auth/ receives only Principal and Role.
"""

from app.core.auth.principal import Principal, Role

__all__ = ["Principal", "Role"]
