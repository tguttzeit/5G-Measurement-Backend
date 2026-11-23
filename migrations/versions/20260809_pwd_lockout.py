"""Add failed_password_attempts column to user table for change-password lockout.

Revision ID: 20260809_pwd_lockout
Revises: 20260809_add_device_commands
Create Date: 2026-08-09 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260809_pwd_lockout"
down_revision: str | None = "20260809_add_device_commands"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("failed_password_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("user", "failed_password_attempts", server_default=None)


def downgrade() -> None:
    op.drop_column("user", "failed_password_attempts")
