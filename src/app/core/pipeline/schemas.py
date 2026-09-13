from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_TARGET_KINDS: frozenset[str] = frozenset(
    {"domain", "ipv4", "ipv6", "cidr", "keyword", "brand_name", "app_store_url"}
)


class TargetCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: str = Field(..., min_length=1, max_length=32)
    value: str = Field(..., min_length=1, max_length=2048)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        v = value.strip().lower()
        if v not in ALLOWED_TARGET_KINDS:
            raise ValueError(f"kind must be one of {sorted(ALLOWED_TARGET_KINDS)}")
        return v


class CollectionLinks(BaseModel):
    self: str
    next: str | None = None


class TargetAttributes(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    value: str
    value_normalized: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
