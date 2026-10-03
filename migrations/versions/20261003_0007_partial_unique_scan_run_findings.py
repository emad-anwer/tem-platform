"""Use a partial unique index for linked scan-run findings.

Revision ID: 20261003_0007
Revises: 20260929_0006
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261003_0007"
down_revision: str | Sequence[str] | None = "20260929_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEX_NAME = "uq_scan_run_findings_tenant_run_finding"
_INDEX_COLUMNS = ["tenant_id", "scan_run_id", "finding_id"]


def upgrade() -> None:
    op.drop_constraint(
        _INDEX_NAME,
        "scan_run_findings",
        type_="unique",
    )
    op.create_index(
        _INDEX_NAME,
        "scan_run_findings",
        _INDEX_COLUMNS,
        unique=True,
        postgresql_where=sa.text("finding_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="scan_run_findings")
    op.create_unique_constraint(
        _INDEX_NAME,
        "scan_run_findings",
        _INDEX_COLUMNS,
        postgresql_nulls_not_distinct=True,
    )
