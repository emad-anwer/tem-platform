"""Identity types — the only representation of 'who is making this request'.

Nothing outside core/auth/ may import a JWT library or reference Zitadel claims.
"""

from __future__ import annotations

import dataclasses
import enum
import uuid


class Role(enum.StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    OWNER = "owner"
    ANALYST = "analyst"
    VIEWER = "viewer"
    SYSTEM = "system"  # for background jobs, not a real user


@dataclasses.dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated identity for the current request.

    This is the ONLY object the rest of the codebase sees.
    It does not leak token format, IdP vendor, or claim names.
    """

    user_id: str  # Zitadel user ID (sub claim) — opaque to consumers
    tenant_id: uuid.UUID  # OUR tenant UUID, not the Zitadel org ID
    role: Role  # owner | analyst | viewer
