from dataclasses import dataclass

from app.core.models import Tenant


@dataclass(frozen=True, slots=True)
class TenantProvisioningResult:
    tenant: Tenant
    created: bool
