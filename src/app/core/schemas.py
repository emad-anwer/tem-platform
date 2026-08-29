from __future__ import annotations

from datetime import datetime
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


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime


class TenantListResponse(BaseModel):
    items: list[TenantResponse]
    pagination: dict[str, int]
