from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID
from alembic.environment import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.pipeline.validation import TargetKind

ALLOWED_TARGET_KINDS: frozenset[str] = frozenset(
    {"domain", "ipv4", "ipv6", "cidr", "keyword", "brand_name", "app_store_url"}
)


class TargetCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: TargetKind
    value: str = Field(..., min_length=1, max_length=2048)

    @field_validator("kind", mode="before")
    @classmethod
    def _normalize_kind_casing(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value


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


class TargetResource(BaseModel):
    type: Literal["targets"] = "targets"
    id: UUID
    attributes: TargetAttributes

    @classmethod
    def from_model(cls, target: Any) -> "TargetResource":
        return cls(id=target.id, attributes=TargetAttributes.model_validate(target))


class TargetDocument(BaseModel):
    data: TargetResource


class TargetCollectionDocument(BaseModel):
    data: list[TargetResource]
    links: CollectionLinks
