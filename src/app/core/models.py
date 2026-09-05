"""Shared SQLAlchemy models for the platform."""

from datetime import datetime
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
