"""Add current_config column to heartbeats.

Revision ID: 20260812_heartbeat_current_cfg
Revises: 20260811_add_campaigns_table
Create Date: 2026-08-12 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to 30 chars: alembic_version.version_num is varchar(32), and every other revision id in
# this directory is well under that limit too.
revision: str = "20260812_heartbeat_current_cfg"
down_revision: str | None = "20260811_add_campaigns_table"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("heartbeats", sa.Column("current_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("heartbeats", "current_config")
