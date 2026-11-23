"""Add latency_results table for storing device latency test results.

Revision ID: 20260809_add_latency_results
Revises: 20260806_add_measurements_table
Create Date: 2026-08-09 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260809_add_latency_results"
down_revision: str | None = "20260806_add_measurements_table"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create latency_results table for storing device latency test results."""
    op.create_table(
        "latency_results",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("device_id", sa.String(length=255), nullable=False),
        sa.Column("test_type", sa.String(length=20), nullable=False),
        sa.Column("flent_test", sa.String(length=255), nullable=False),
        sa.Column("mission_type", sa.String(length=255), nullable=False),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_fix", postgresql.JSONB(), nullable=False),
        sa.Column("end_fix", postgresql.JSONB(), nullable=False),
        sa.Column("baseline_rtt_ms", sa.Float(), nullable=True),
        sa.Column("rtt_under_load_ms", sa.Float(), nullable=True),
        sa.Column("rtt_p99_ms", sa.Float(), nullable=True),
        sa.Column("download_mbits_s", sa.Float(), nullable=True),
        sa.Column("upload_mbits_s", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("idx_latency_results_device_timestamp"),
        "latency_results",
        ["device_id", "start_timestamp"],
    )
    op.create_index(
        op.f("ix_latency_results_device_id"), "latency_results", ["device_id"]
    )
    op.create_index(
        op.f("ix_latency_results_test_type"), "latency_results", ["test_type"]
    )


def downgrade() -> None:
    """Drop latency_results table."""
    op.drop_index(op.f("ix_latency_results_test_type"), table_name="latency_results")
    op.drop_index(op.f("ix_latency_results_device_id"), table_name="latency_results")
    op.drop_index(op.f("idx_latency_results_device_timestamp"), table_name="latency_results")
    op.drop_table("latency_results")
