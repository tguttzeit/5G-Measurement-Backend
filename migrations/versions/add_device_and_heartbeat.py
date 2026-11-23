"""Add Device and Heartbeat models

Revision ID: add_device_and_heartbeat
Revises: fb09209eef66
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_device_and_heartbeat"
down_revision: Union[str, Sequence[str], None] = "fb09209eef66"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add Device and Heartbeat tables."""
    # Create devices table
    op.create_table(
        "devices",
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("api_key_hash", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("device_id"),
    )

    # Create heartbeats table
    op.create_table(
        "heartbeats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("datapoints_total", sa.BigInteger(), nullable=False),
        sa.Column("datapoints_good", sa.BigInteger(), nullable=False),
        sa.Column("datapoints_bad", sa.BigInteger(), nullable=False),
        sa.Column("datapoints_invalid", sa.BigInteger(), nullable=False),
        sa.Column("pipeline_broken", sa.Boolean(), nullable=False),
        sa.Column("storage_pending_files", sa.BigInteger(), nullable=False),
        sa.Column("storage_disk_free_bytes", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.device_id"],
            ondelete="CASCADE",
        ),
    )

    # Create index on (device_id, received_at) for efficient latest-heartbeat queries
    op.create_index(
        "ix_heartbeats_device_received",
        "heartbeats",
        ["device_id", "received_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema by removing Device and Heartbeat tables."""
    op.drop_index("ix_heartbeats_device_received", table_name="heartbeats")
    op.drop_table("heartbeats")
    op.drop_table("devices")
