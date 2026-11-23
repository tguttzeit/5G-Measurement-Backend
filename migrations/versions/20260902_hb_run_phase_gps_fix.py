"""Add run_phase and gps_fix columns to heartbeats.

Revision ID: 20260902_heartbeat_run_phase_gps_fix
Revises: 20260825_add_gps_fix_test_status
Create Date: 2026-09-02 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to 30 chars: alembic_version.version_num is varchar(32), and every other revision id in
# this directory is well under that limit too.
revision: str = "20260902_hb_run_phase_gps_fix"
down_revision: str | None = "20260825_add_gps_fix_test_status"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("heartbeats", sa.Column("run_phase", sa.String(), nullable=True))
    op.add_column("heartbeats", sa.Column("gps_fix", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("heartbeats", "gps_fix")
    op.drop_column("heartbeats", "run_phase")
