"""Add user_favorite_config_fields, the Remote Configuration fields each user marked as favorite.

Revision ID: 20261030_favorite_config_fields
Revises: 20261030_hb_critical_error
Create Date: 2026-10-30 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261030_favorite_config_fields"
down_revision: str | None = "20261030_hb_critical_error"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "user_favorite_config_fields",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("field_key", sa.String(length=100), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("user_favorite_config_fields")
