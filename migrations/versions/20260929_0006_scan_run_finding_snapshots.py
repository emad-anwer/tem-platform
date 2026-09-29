"""Persist immutable finding snapshots for scan-run change reports.

Revision ID: 20260929_0006
Revises: 20260907_0005
Create Date: 2026-09-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260929_0006"
down_revision: str | Sequence[str] | None = "20260907_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_run_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("scan_run_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=True),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column(
            "finding_snapshot",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["scan_run_id"], ["scan_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"], ["findings.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "scan_run_id",
            "finding_id",
            name="uq_scan_run_findings_tenant_run_finding",
        ),
    )
    op.create_index(
        op.f("ix_scan_run_findings_tenant_id"),
        "scan_run_findings",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_scan_run_findings_tenant_run_classification",
        "scan_run_findings",
        ["tenant_id", "scan_run_id", "classification"],
        unique=False,
    )
    op.create_index(
        "ix_scan_run_findings_tenant_run_created_at_id",
        "scan_run_findings",
        ["tenant_id", "scan_run_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scan_run_findings_tenant_run_created_at_id",
        table_name="scan_run_findings",
    )
    op.drop_index(
        "ix_scan_run_findings_tenant_run_classification",
        table_name="scan_run_findings",
    )
    op.drop_index(op.f("ix_scan_run_findings_tenant_id"), table_name="scan_run_findings")
    op.drop_table("scan_run_findings")
