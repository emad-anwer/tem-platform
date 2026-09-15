from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.jobs.states import ErrorKind, ScanRunStatus
from app.core.pipeline.validation import TargetKind


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
    def from_model(cls, target: Any) -> TargetResource:
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
    def from_model(cls, run: Any) -> ScanRunResource:
        return cls(id=run.id, attributes=ScanRunAttributes.model_validate(run))


class ScanRunDocument(BaseModel):
    data: ScanRunResource


###########Findings#########
class FindingAttributes(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_id: UUID
    last_seen_run_id: UUID | None
    kind: str
    value: str
    value_normalized: str
    fingerprint: str
    severity: str
    raw_severity: str | None
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    times_seen: int
    details: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class FindingResource(BaseModel):
    type: Literal["findings"] = "findings"
    id: UUID
    attributes: FindingAttributes

    @classmethod
    def from_model(cls, finding: Any) -> FindingResource:
        return cls(id=finding.id, attributes=FindingAttributes.model_validate(finding))


class FindingCollectionDocument(BaseModel):
    data: list[FindingResource]
    links: CollectionLinks
