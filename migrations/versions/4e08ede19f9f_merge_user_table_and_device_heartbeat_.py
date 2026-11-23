"""merge user table and device/heartbeat branches

Revision ID: 4e08ede19f9f
Revises: 20260805_add_user_table, add_device_and_heartbeat
Create Date: 2026-08-06 09:38:36.554097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e08ede19f9f'
down_revision: Union[str, Sequence[str], None] = ('20260805_add_user_table', 'add_device_and_heartbeat')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
