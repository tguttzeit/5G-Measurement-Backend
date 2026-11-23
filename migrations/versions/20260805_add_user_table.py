"""add user table

Revision ID: 20260805_add_user_table
Revises: fb09209eef66
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260805_add_user_table"
down_revision: Union[str, Sequence[str], None] = "fb09209eef66"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True, index=True),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, default=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False, default=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("user")
