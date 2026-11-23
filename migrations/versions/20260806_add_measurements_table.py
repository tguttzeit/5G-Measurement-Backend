"""Add measurements table for storing device datapoints.

Revision ID: 20260806_add_measurements_table
Revises: 4e08ede19f9f
Create Date: 2026-08-06 00:00:00.000000

"""

from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260806_add_measurements_table"
down_revision: str | None = "add_test_results_table"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create measurements table for storing device datapoints."""
    op.create_table(
        "measurements",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.String(length=255), nullable=False),
        sa.Column("mission_type", sa.String(length=255), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("placeholder", sa.Boolean(), nullable=False, default=False),
        sa.Column("rsrp", sa.Float(), nullable=True),
        sa.Column("rsrq", sa.Float(), nullable=True),
        sa.Column("sinr", sa.Float(), nullable=True),
        sa.Column("rat", sa.String(length=50), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    
    # Create indexes for common query patterns
    op.create_index(op.f("idx_measurements_device_timestamp"), "measurements", ["device_id", "timestamp"])
    op.create_index(op.f("idx_measurements_geo"), "measurements", ["latitude", "longitude"])
    op.create_index(op.f("idx_measurements_quality"), "measurements", ["rsrp", "rsrq", "sinr"])
    op.create_index(op.f("idx_measurements_timestamp"), "measurements", ["timestamp"])
    op.create_index(op.f("idx_measurements_device_id"), "measurements", ["device_id"])


def downgrade() -> None:
    """Drop measurements table."""
    op.drop_index(op.f("idx_measurements_device_id"), table_name="measurements")
    op.drop_index(op.f("idx_measurements_timestamp"), table_name="measurements")
    op.drop_index(op.f("idx_measurements_quality"), table_name="measurements")
    op.drop_index(op.f("idx_measurements_geo"), table_name="measurements")
    op.drop_index(op.f("idx_measurements_device_timestamp"), table_name="measurements")
    op.drop_table("measurements")