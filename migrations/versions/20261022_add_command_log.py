"""Add command_log, the persisted history of command/override communication.

Revision ID: 20261022_add_command_log
Revises: 20261013_add_run_id
Create Date: 2026-10-22 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261022_add_command_log"
down_revision: str | None = "20261013_add_run_id"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "command_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "device_id",
            sa.String(),
            sa.ForeignKey("devices.device_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("command_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_command_log_device_occurred", "command_log", ["device_id", "occurred_at"]
    )
    op.create_index("ix_command_log_occurred", "command_log", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_command_log_occurred", table_name="command_log")
    op.drop_index("ix_command_log_device_occurred", table_name="command_log")
    op.drop_table("command_log")
