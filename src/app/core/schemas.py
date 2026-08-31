from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TenantCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        if not value:
            raise ValueError("slug is required")
        if not value.islower():
            raise ValueError("slug must be lowercase")
        if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in value):
            raise ValueError("slug may only contain lowercase letters, numbers, and hyphens")
        if value.startswith("-") or value.endswith("-"):
            raise ValueError("slug must not start or end with a hyphen")
        return value


class TenantAttributes(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    slug: str
    is_active: bool
    created_at: datetime


class TenantResource(BaseModel):
    """A JSON:API resource object for a tenant."""

    type: Literal["tenants"] = "tenants"
    id: UUID
    attributes: TenantAttributes

    @classmethod
    def from_tenant(cls, tenant: Any) -> TenantResource:
        tenant_id = tenant["id"] if isinstance(tenant, dict) else tenant.id
        return cls(id=tenant_id, attributes=TenantAttributes.model_validate(tenant))


class TenantDocument(BaseModel):
    """A JSON:API document wrapping a single tenant resource."""

    data: TenantResource


class TenantCollectionLinks(BaseModel):
    self: str
    next: str | None = None


class TenantCollectionDocument(BaseModel):
    """A JSON:API document wrapping a page of tenant resources."""

    data: list[TenantResource]
    links: TenantCollectionLinks
