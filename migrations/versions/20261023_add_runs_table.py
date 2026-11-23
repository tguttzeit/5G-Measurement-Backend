"""Add the runs table and define campaigns by their assigned runs instead of a date range.

Every distinct (device_id, run_id) in measurements gets a runs row. Existing date-range campaigns
are converted: a run is assigned to the campaign whose range contains the UTC day of the run's
first measurement; where ranges overlap, the campaign with the earliest start_date (then lowest
id) wins, so each run ends up in at most one campaign. The campaign date columns are dropped
afterwards. Alembic runs the whole migration in one transaction.

Downgrade restores start_date/end_date as the UTC days of the oldest and newest measurement of the
campaign's runs; a campaign without runs gets the day of the downgrade for both.

Revision ID: 20261023_add_runs_table
Revises: 20261023_add_app_settings
Create Date: 2026-10-23 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261023_add_runs_table"
down_revision: str | None = "20261023_add_app_settings"
branch_labels: str | None = None
depends_on: str | None = None

RUN_ID_COLUMN_LENGTH = 600


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=RUN_ID_COLUMN_LENGTH), nullable=False),
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("device_id", "run_id", name="uq_runs_device_run"),
    )
    op.create_index("ix_runs_campaign_id", "runs", ["campaign_id"])

    op.execute(
        """
        INSERT INTO runs (device_id, run_id)
        SELECT DISTINCT device_id, run_id FROM measurements
        """
    )
    op.execute(
        """
        UPDATE runs
        SET campaign_id = (
            SELECT campaigns.id FROM campaigns
            WHERE campaigns.start_date <= run_starts.start_day
              AND campaigns.end_date >= run_starts.start_day
            ORDER BY campaigns.start_date, campaigns.id
            LIMIT 1
        )
        FROM (
            SELECT device_id, run_id, (min(timestamp) AT TIME ZONE 'UTC')::date AS start_day
            FROM measurements
            GROUP BY device_id, run_id
        ) AS run_starts
        WHERE runs.device_id = run_starts.device_id AND runs.run_id = run_starts.run_id
        """
    )

    op.drop_index("idx_campaigns_date_range", table_name="campaigns")
    op.drop_column("campaigns", "start_date")
    op.drop_column("campaigns", "end_date")


def downgrade() -> None:
    op.add_column("campaigns", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("campaigns", sa.Column("end_date", sa.Date(), nullable=True))
    op.execute(
        """
        UPDATE campaigns
        SET start_date = campaign_periods.start_day, end_date = campaign_periods.end_day
        FROM (
            SELECT runs.campaign_id,
                   (min(measurements.timestamp) AT TIME ZONE 'UTC')::date AS start_day,
                   (max(measurements.timestamp) AT TIME ZONE 'UTC')::date AS end_day
            FROM runs
            JOIN measurements
              ON measurements.device_id = runs.device_id AND measurements.run_id = runs.run_id
            WHERE runs.campaign_id IS NOT NULL
            GROUP BY runs.campaign_id
        ) AS campaign_periods
        WHERE campaigns.id = campaign_periods.campaign_id
        """
    )
    op.execute(
        """
        UPDATE campaigns
        SET start_date = CURRENT_DATE, end_date = CURRENT_DATE
        WHERE start_date IS NULL
        """
    )
    op.alter_column("campaigns", "start_date", nullable=False)
    op.alter_column("campaigns", "end_date", nullable=False)
    op.create_index("idx_campaigns_date_range", "campaigns", ["start_date", "end_date"])

    op.drop_index("ix_runs_campaign_id", table_name="runs")
    op.drop_table("runs")
