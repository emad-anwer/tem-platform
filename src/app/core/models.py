"""Shared SQLAlchemy models for the platform."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""


class TenantOwnedMixin:
    """Mixin providing a tenant_id foreign key column and index for tenant-scoped entities."""

    @declared_attr
    def tenant_id(cls) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


class Tenant(Base):
    """An organization that owns data in the platform."""

    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    zitadel_org_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
        default=None,
    )


class ProvisioningStatus(StrEnum):
    # Key claimed but zitadel org is not yet created
    IN_PROGRESS = "in_progress"

    # Zitadel org is created but local insert is not yet done
    ORG_CREATED = "org_created"

    # Local tenant row exists
    COMPLETED = "completed"


class TenantProvisioningAttempt(Base):
    """Tracks the status of tenant provisioning attempts."""

    __tablename__ = "tenant_provisioning_attempts"

    idempotency_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    zitadel_org_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True
    )
    status: Mapped[ProvisioningStatus] = mapped_column(
        String(20), nullable=False, default=ProvisioningStatus.IN_PROGRESS
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Target(Base, TenantOwnedMixin):
    """A target domain, IP, CIDR, keyword, brand name, or app store URL."""

    __tablename__ = "targets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "kind",
            "value_normalized",
            name="uq_targets_tenant_kind_value_norm",
        ),
        Index("ix_targets_tenant_kind", "tenant_id", "kind"),
        Index("ix_targets_tenant_created_at_id", "tenant_id", "created_at", "id"),
    )


class ScanRun(Base, TenantOwnedMixin):
    """The honest execution record of a scan against a target."""

    __tablename__ = "scan_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="queued", server_default="queued"
    )
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    arq_job_id: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    sources_attempted: Mapped[list[Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        server_default="[]",
    )
    sources_degraded: Mapped[list[Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        server_default="[]",
    )
    findings_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    new_findings_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    error_kind: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(
        String(2000), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_scan_runs_tenant_target_created", "tenant_id", "target_id", "created_at"
        ),
        Index("ix_scan_runs_tenant_created_at_id", "tenant_id", "created_at", "id"),
    )


class Finding(Base, TenantOwnedMixin):
    """A normalized security finding discovered by a scan."""

    __tablename__ = "findings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), nullable=False
    )
    last_seen_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="SET NULL"), nullable=True, default=None
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    raw_severity: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="active", server_default="active"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    times_seen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "fingerprint", name="uq_findings_tenant_fingerprint"
        ),
        Index(
            "ix_findings_tenant_target_last_seen",
            "tenant_id",
            "target_id",
            "last_seen_at",
        ),
        Index("ix_findings_tenant_run", "tenant_id", "last_seen_run_id"),
        Index("ix_findings_tenant_kind_severity", "tenant_id", "kind", "severity"),
        Index("ix_findings_tenant_status", "tenant_id", "status"),
        Index("ix_findings_tenant_created_at_id", "tenant_id", "created_at", "id"),
    )
