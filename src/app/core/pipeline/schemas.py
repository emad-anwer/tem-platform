from __future__ import annotations

from datetime import datetime
from typing import Literal, Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.jobs.states import ScanRunStatus, ErrorKind
from app.core.pipeline.validation import TargetKind

ALLOWED_TARGET_KINDS: frozenset[str] = frozenset(
    {"domain", "ipv4", "ipv6", "cidr", "keyword", "brand_name", "app_store_url"}
)


######### Targets #########
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


##########Scan Runs##########
class ScanRunAttributes(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_id: UUID
    status: ScanRunStatus
    attempt: int
    max_attempts: int
    arq_job_id: str | None
    sources_attempted: list[Any]
    sources_degraded: list[Any]
    findings_count: int
    new_findings_count: int
    started_at: datetime | None
    finished_at: datetime | None
    error_kind: ErrorKind | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ScanRunResource(BaseModel):
    # NOTE: type "scan_runs" per ADR-0003 §9. If your team wants the issue's
    # literal "/scans" path instead, change this Literal to "scans" too, to
    # keep the JSON:API `type` consistent with the path.
    type: Literal["scan_runs"] = "scan_runs"
    id: UUID
    attributes: ScanRunAttributes

    @classmethod
    def from_model(cls, run: Any) -> "ScanRunResource":
        return cls(id=run.id, attributes=ScanRunAttributes.model_validate(run))


class ScanRunDocument(BaseModel):
    data: ScanRunResource
