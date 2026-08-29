"""Backward-compatible imports for the tenant API.

The actual implementation lives in the dedicated core modules:
- app.core.schemas
- app.core.service
- app.core.repository
- app.core.routes
"""

from app.core.routes import router
from app.core.schemas import TenantCreateRequest, TenantListResponse, TenantResponse
from app.core.service import TenantService, get_tenant_service

__all__ = [
    "TenantCreateRequest",
    "TenantListResponse",
    "TenantResponse",
    "TenantService",
    "get_tenant_service",
    "router",
]
