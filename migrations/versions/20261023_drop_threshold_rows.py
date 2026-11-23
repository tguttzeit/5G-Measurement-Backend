"""Delete queued config overrides of the removed rsrp/rsrq/sinr threshold fields.

Revision ID: 20261023_drop_threshold_rows
Revises: 20261023_add_runs_table
Create Date: 2026-10-23 12:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261023_drop_threshold_rows"
down_revision: str | None = "20261023_add_runs_table"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # The fields are no longer delivered, so their queued rows would only show up as stale
    # entries. command_log keeps the history.
    op.execute(
        "DELETE FROM device_commands WHERE type = 'config_override' "
        "AND field IN ('rsrp_threshold', 'rsrq_threshold', 'sinr_threshold')"
    )


def downgrade() -> None:
    # Deleted queue rows cannot be recovered.
    pass
