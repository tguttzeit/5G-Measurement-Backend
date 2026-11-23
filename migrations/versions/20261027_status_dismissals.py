"""Add command_status_dismissals, which hides finished commands from the command status.

Revision ID: 20261027_status_dismissals
Revises: 20261026_normalize_runs
Create Date: 2026-10-27 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261027_status_dismissals"
down_revision: str | None = "20261026_normalize_runs"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "command_status_dismissals",
        sa.Column(
            "device_id",
            sa.String(),
            sa.ForeignKey("devices.device_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("command_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column(
            "dismissed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("command_status_dismissals")
