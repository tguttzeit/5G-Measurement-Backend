"""Add critical_error column to heartbeats.

Revision ID: 20261030_hb_critical_error
Revises: 20261027_status_dismissals
Create Date: 2026-10-30 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261030_hb_critical_error"
down_revision: str | None = "20261027_status_dismissals"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("heartbeats", sa.Column("critical_error", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("heartbeats", "critical_error")
