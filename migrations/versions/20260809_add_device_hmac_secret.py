"""Add hmac_secret column to devices, for signing heartbeat responses.

Revision ID: 20260809_add_device_hmac_secret
Revises: 20260809_add_latency_results
Create Date: 2026-08-09 00:00:00.000000

"""
import secrets

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260809_add_device_hmac_secret"
down_revision: str | None = "20260809_add_latency_results"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add hmac_secret, backfilling any existing devices with a fresh random secret."""
    op.add_column("devices", sa.Column("hmac_secret", sa.String(), nullable=True))

    conn = op.get_bind()
    existing_devices = conn.execute(
        sa.text("SELECT device_id FROM devices WHERE hmac_secret IS NULL")
    ).fetchall()
    for (device_id,) in existing_devices:
        conn.execute(
            sa.text("UPDATE devices SET hmac_secret = :secret WHERE device_id = :device_id"),
            {"secret": secrets.token_hex(32), "device_id": device_id},
        )

    op.alter_column("devices", "hmac_secret", nullable=False)


def downgrade() -> None:
    """Drop hmac_secret."""
    op.drop_column("devices", "hmac_secret")
