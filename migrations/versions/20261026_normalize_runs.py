"""Normalize runs: attributes live on `runs`, measurement rows reference a run by foreign key.

`runs` gains `name` (user-editable, nullable) and `mission_type`. `measurements` and
`latency_results` get `run_pk`, a foreign key to `runs.id` with `ON DELETE CASCADE`, and lose the
`run_id` and `mission_type` columns that duplicated the run. `device_id` stays on the rows.

Every distinct (device_id, run_id) of both tables gets a runs row (measurement runs already have
one). A run's mission type is the smallest mission type among its measurements, or among its
latency results for a run that has none. Alembic runs the whole migration in one transaction.

Downgrade writes the run's mission type and device-supplied run_id back onto every row.

Revision ID: 20261026_normalize_runs
Revises: 20261023_drop_threshold_rows
Create Date: 2026-10-26 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261026_normalize_runs"
down_revision: str | None = "20261023_drop_threshold_rows"
branch_labels: str | None = None
depends_on: str | None = None

RUN_ID_COLUMN_LENGTH = 600

# table name -> the timestamp column that dates a row
TABLES = {"measurements": "timestamp", "latency_results": "start_timestamp"}


def upgrade() -> None:
    op.add_column("runs", sa.Column("name", sa.String(length=255), nullable=True))
    op.add_column("runs", sa.Column("mission_type", sa.String(length=255), nullable=True))

    op.execute(
        """
        INSERT INTO runs (device_id, run_id)
        SELECT DISTINCT device_id, run_id FROM latency_results
        ON CONFLICT (device_id, run_id) DO NOTHING
        """
    )
    for table in TABLES:
        op.execute(
            f"""
            UPDATE runs
            SET mission_type = run_mission_types.mission_type
            FROM (
                SELECT device_id, run_id, min(mission_type) AS mission_type
                FROM {table}
                GROUP BY device_id, run_id
            ) AS run_mission_types
            WHERE runs.mission_type IS NULL
              AND runs.device_id = run_mission_types.device_id
              AND runs.run_id = run_mission_types.run_id
            """
        )
    op.alter_column("runs", "mission_type", nullable=False)

    for table in TABLES:
        op.add_column(table, sa.Column("run_pk", sa.Integer(), nullable=True))
        op.execute(
            f"""
            UPDATE {table}
            SET run_pk = runs.id
            FROM runs
            WHERE runs.device_id = {table}.device_id AND runs.run_id = {table}.run_id
            """
        )
        op.alter_column(table, "run_pk", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_run_pk_runs", table, "runs", ["run_pk"], ["id"], ondelete="CASCADE"
        )
        op.create_index(f"ix_{table}_run_pk", table, ["run_pk"])

    op.drop_index("idx_measurements_device_run", table_name="measurements")
    op.drop_index("idx_latency_results_device_run", table_name="latency_results")
    for table in TABLES:
        op.drop_index(f"ix_{table}_run_id", table_name=table)
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_mission_type")
        op.drop_column(table, "run_id")
        op.drop_column(table, "mission_type")


def downgrade() -> None:
    for table, timestamp_column in TABLES.items():
        op.add_column(table, sa.Column("run_id", sa.String(length=RUN_ID_COLUMN_LENGTH)))
        op.add_column(table, sa.Column("mission_type", sa.String(length=255)))
        op.execute(
            f"""
            UPDATE {table}
            SET run_id = runs.run_id, mission_type = runs.mission_type
            FROM runs
            WHERE runs.id = {table}.run_pk
            """
        )
        op.alter_column(table, "run_id", nullable=False)
        op.alter_column(table, "mission_type", nullable=False)
        op.create_index(f"ix_{table}_run_id", table, ["run_id"])
        op.drop_index(f"ix_{table}_run_pk", table_name=table)
        op.drop_constraint(f"fk_{table}_run_pk_runs", table, type_="foreignkey")
        op.drop_column(table, "run_pk")

    op.create_index("idx_measurements_device_run", "measurements", ["device_id", "run_id"])
    op.create_index("idx_latency_results_device_run", "latency_results", ["device_id", "run_id"])
    op.create_index("ix_measurements_mission_type", "measurements", ["mission_type"])

    op.drop_column("runs", "mission_type")
    op.drop_column("runs", "name")
