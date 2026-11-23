"""Add app_settings, a generic key/value table for runtime-changeable application settings.

Revision ID: 20261023_add_app_settings
Revises: 20261023_heartbeat_valid_count
Create Date: 2026-10-23 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261023_add_app_settings"
down_revision: str | None = "20261023_heartbeat_valid_count"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=63), primary_key=True),
        sa.Column("value", sa.JSON(none_as_null=False), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
