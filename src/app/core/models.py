"""Shared SQLAlchemy models for the platform."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
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
