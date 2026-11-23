"""Add gps_fix_test_status table for the live GPS-fix-finding diagnostic.

Revision ID: 20260825_add_gps_fix_test_status
Revises: 20260812_heartbeat_current_cfg
Create Date: 2026-08-25 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260825_add_gps_fix_test_status"
down_revision: str | None = "20260812_heartbeat_current_cfg"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "gps_fix_test_status",
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("num_satellites", sa.Integer(), nullable=False),
        sa.Column("has_fix", sa.Boolean(), nullable=False),
        sa.Column("elapsed_s", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )


def downgrade() -> None:
    op.drop_table("gps_fix_test_status")
