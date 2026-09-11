"""Create pipeline tables: targets, scan_runs, findings.

Revision ID: 20260907_0005
Revises: 5f1f2b964058
Create Date: 2026-09-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260907_0005"
down_revision: str | Sequence[str] | None = "5f1f2b964058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ----------------------------------------------------------------------
    # 1. targets
    # ----------------------------------------------------------------------
    op.create_table(
        "targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_normalized", sa.Text(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "tenant_id",
            "kind",
            "value_normalized",
            name="uq_targets_tenant_kind_value_norm",
        ),
    )
    op.create_index(
        op.f("ix_targets_tenant_id"), "targets", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_targets_tenant_kind", "targets", ["tenant_id", "kind"], unique=False
    )
    op.create_index(
        "ix_targets_tenant_created_at_id",
        "targets",
        ["tenant_id", "created_at", "id"],
        unique=False,
    )

    # ----------------------------------------------------------------------
    # 2. scan_runs
    # ----------------------------------------------------------------------
    op.create_table(
        "scan_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("arq_job_id", sa.Text(), nullable=True),
        sa.Column(
            "sources_attempted",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "sources_degraded",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "findings_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "new_findings_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_kind", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
    )
    op.create_index(
        op.f("ix_scan_runs_tenant_id"), "scan_runs", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_scan_runs_tenant_target_created",
        "scan_runs",
        ["tenant_id", "target_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_scan_runs_tenant_created_at_id",
        "scan_runs",
        ["tenant_id", "created_at", "id"],
        unique=False,
    )

    # ----------------------------------------------------------------------
    # 3. findings
    # ----------------------------------------------------------------------
    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("last_seen_run_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_normalized", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("raw_severity", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "times_seen", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["last_seen_run_id"], ["scan_runs.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "tenant_id", "fingerprint", name="uq_findings_tenant_fingerprint"
        ),
    )
    op.create_index(
        op.f("ix_findings_tenant_id"), "findings", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_findings_tenant_target_last_seen",
        "findings",
        ["tenant_id", "target_id", "last_seen_at"],
        unique=False,
    )
    op.create_index(
        "ix_findings_tenant_run",
        "findings",
        ["tenant_id", "last_seen_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_findings_tenant_kind_severity",
        "findings",
        ["tenant_id", "kind", "severity"],
        unique=False,
    )
    op.create_index(
        "ix_findings_tenant_status", "findings", ["tenant_id", "status"], unique=False
    )
    op.create_index(
        "ix_findings_tenant_created_at_id",
        "findings",
        ["tenant_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_findings_tenant_created_at_id", table_name="findings")
    op.drop_index("ix_findings_tenant_status", table_name="findings")
    op.drop_index("ix_findings_tenant_kind_severity", table_name="findings")
    op.drop_index("ix_findings_tenant_run", table_name="findings")
    op.drop_index("ix_findings_tenant_target_last_seen", table_name="findings")
    op.drop_index(op.f("ix_findings_tenant_id"), table_name="findings")
    op.drop_table("findings")

    op.drop_index("ix_scan_runs_tenant_created_at_id", table_name="scan_runs")
    op.drop_index("ix_scan_runs_tenant_target_created", table_name="scan_runs")
    op.drop_index(op.f("ix_scan_runs_tenant_id"), table_name="scan_runs")
    op.drop_table("scan_runs")

    op.drop_index("ix_targets_tenant_created_at_id", table_name="targets")
    op.drop_index("ix_targets_tenant_kind", table_name="targets")
    op.drop_index(op.f("ix_targets_tenant_id"), table_name="targets")
    op.drop_table("targets")
