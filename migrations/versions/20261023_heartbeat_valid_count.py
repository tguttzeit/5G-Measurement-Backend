"""Replace Heartbeat.datapoints_good/bad with datapoints_valid.

Revision ID: 20261023_heartbeat_valid_count
Revises: 20261022_add_command_log
Create Date: 2026-10-23 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261023_heartbeat_valid_count"
down_revision: str | None = "20261022_add_command_log"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("heartbeats", sa.Column("datapoints_valid", sa.BigInteger(), nullable=True))
    op.execute("UPDATE heartbeats SET datapoints_valid = datapoints_good + datapoints_bad")
    op.alter_column("heartbeats", "datapoints_valid", nullable=False)
    op.drop_column("heartbeats", "datapoints_good")
    op.drop_column("heartbeats", "datapoints_bad")


def downgrade() -> None:
    # The good/bad split cannot be recovered; everything valid is reported as good.
    op.add_column("heartbeats", sa.Column("datapoints_good", sa.BigInteger(), nullable=True))
    op.add_column("heartbeats", sa.Column("datapoints_bad", sa.BigInteger(), nullable=True))
    op.execute("UPDATE heartbeats SET datapoints_good = datapoints_valid, datapoints_bad = 0")
    op.alter_column("heartbeats", "datapoints_good", nullable=False)
    op.alter_column("heartbeats", "datapoints_bad", nullable=False)
    op.drop_column("heartbeats", "datapoints_valid")
