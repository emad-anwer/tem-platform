"""Initial migration.

Revision ID: 20260826_0001
Revises:
Create Date: 2026-08-26

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20260826_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
