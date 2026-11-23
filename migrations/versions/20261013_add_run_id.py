"""Add run_id to measurements and latency_results, backfilling existing rows.

Existing rows get one synthetic run per (device_id, mission_type, UTC calendar date), with the id
format `legacy-<device_id>-<mission_type>-<YYYY-MM-DD>` that app.run_ids.legacy_run_id also
produces for uploads without a run_id. The backfill only touches rows where run_id is still NULL,
so re-running it is a no-op. Alembic runs the whole migration in one transaction.

Revision ID: 20261013_add_run_id
Revises: 20261006_latency_idempotency
Create Date: 2026-10-13 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261013_add_run_id"
down_revision: str | None = "20261006_latency_idempotency"
branch_labels: str | None = None
depends_on: str | None = None

RUN_ID_COLUMN_LENGTH = 600

# table name -> the timestamp column that dates a row
TABLES = {"measurements": "timestamp", "latency_results": "start_timestamp"}


def upgrade() -> None:
    for table, timestamp_column in TABLES.items():
        op.add_column(table, sa.Column("run_id", sa.String(length=RUN_ID_COLUMN_LENGTH)))
        op.execute(
            f"""
            UPDATE {table}
            SET run_id = 'legacy-' || device_id || '-' || mission_type || '-'
                || to_char({timestamp_column} AT TIME ZONE 'UTC', 'YYYY-MM-DD')
            WHERE run_id IS NULL
            """
        )
        op.alter_column(table, "run_id", nullable=False)
        op.create_index(f"ix_{table}_run_id", table, ["run_id"])

    op.create_index("idx_measurements_device_run", "measurements", ["device_id", "run_id"])
    op.create_index("idx_latency_results_device_run", "latency_results", ["device_id", "run_id"])


def downgrade() -> None:
    op.drop_index("idx_latency_results_device_run", table_name="latency_results")
    op.drop_index("idx_measurements_device_run", table_name="measurements")
    for table in TABLES:
        op.drop_index(f"ix_{table}_run_id", table_name=table)
        op.drop_column(table, "run_id")
