"""Add campaigns table for backend-defined date-range campaign scoping.

Revision ID: 20260811_add_campaigns_table
Revises: 20260809_pwd_lockout
Create Date: 2026-08-11 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260811_add_campaigns_table"
down_revision: str | None = "20260809_pwd_lockout"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_campaigns_name"), "campaigns", ["name"])
    op.create_index(
        op.f("idx_campaigns_date_range"), "campaigns", ["start_date", "end_date"]
    )


def downgrade() -> None:
    op.drop_index(op.f("idx_campaigns_date_range"), table_name="campaigns")
    op.drop_index(op.f("ix_campaigns_name"), table_name="campaigns")
    op.drop_table("campaigns")
