"""Backward-compatible imports for the tenant API.

The actual implementation lives in the dedicated core modules:
- app.core.schemas
- app.core.service
- app.core.repository
- app.core.routes
"""

from app.core.routes import router
from app.core.schemas import (
    TenantCollectionDocument,
    TenantCreateRequest,
    TenantDocument,
)
from app.core.service import TenantService, get_tenant_service

__all__ = [
    "TenantCollectionDocument",
    "TenantCreateRequest",
    "TenantDocument",
    "TenantService",
    "get_tenant_service",
    "router",
]
