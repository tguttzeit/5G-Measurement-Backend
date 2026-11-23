"""Add user_notification_settings table.

Revision ID: 20261030_user_notif_settings
Revises: 20261030_favorite_config_fields
Create Date: 2026-10-30 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261030_user_notif_settings"
down_revision: str | None = "20261030_favorite_config_fields"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "user_notification_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("topic"),
    )


def downgrade() -> None:
    op.drop_table("user_notification_settings")
