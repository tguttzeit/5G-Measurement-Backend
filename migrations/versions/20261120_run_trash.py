"""Add runs.deleted_at/deleted_by: deleting a run moves it to the trash.

Revision ID: 20261120_run_trash
Revises: 20261030_user_notif_settings
Create Date: 2026-11-20 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261120_run_trash"
down_revision: str | None = "20261030_user_notif_settings"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "runs",
        sa.Column(
            "deleted_by",
            sa.Integer(),
            sa.ForeignKey("user.id", name="fk_runs_deleted_by_user", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_constraint("fk_runs_deleted_by_user", "runs", type_="foreignkey")
    op.drop_column("runs", "deleted_by")
    op.drop_column("runs", "deleted_at")
