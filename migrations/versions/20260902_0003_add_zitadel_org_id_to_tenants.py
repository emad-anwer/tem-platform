"""Add zitadel_org_id to tenants.

Revision ID: 20260902_0003
Revises: 20260827_0002
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260902_0003"
down_revision: str | Sequence[str] | None = "20260827_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("zitadel_org_id", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_tenants_zitadel_org_id", "tenants", ["zitadel_org_id"]
    )
    op.create_index(
        "ix_tenants_zitadel_org_id", "tenants", ["zitadel_org_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_tenants_zitadel_org_id", table_name="tenants")
    op.drop_constraint(
        "uq_tenants_zitadel_org_id", table_name="tenants", type_="unique"
    )
    op.drop_column("tenants", "zitadel_org_id")
