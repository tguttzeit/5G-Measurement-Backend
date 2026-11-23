"""Add idempotency_key column to latency_results, unique per device.

Revision ID: 20261006_latency_idempotency
Revises: 20260902_hb_run_phase_gps_fix
Create Date: 2026-10-06 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261006_latency_idempotency"
down_revision: str | None = "20260902_hb_run_phase_gps_fix"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "latency_results", sa.Column("idempotency_key", sa.String(length=255), nullable=True)
    )
    op.create_unique_constraint(
        "uq_latency_results_device_idempotency_key",
        "latency_results",
        ["device_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_latency_results_device_idempotency_key", "latency_results", type_="unique"
    )
    op.drop_column("latency_results", "idempotency_key")
