"""Add device_commands table for queued config overrides and one-shot commands.

Revision ID: 20260809_add_device_commands
Revises: 20260809_add_device_hmac_secret
Create Date: 2026-08-09 00:00:01.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260809_add_device_commands"
down_revision: str | None = "20260809_add_device_hmac_secret"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create device_commands table."""
    op.create_table(
        "device_commands",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("config_override", "one_shot", name="commandtype"),
            nullable=False,
        ),
        sa.Column("field", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_device_commands_device_id"), "device_commands", ["device_id"]
    )
    op.create_index(
        op.f("ix_device_commands_type"), "device_commands", ["type"]
    )
    op.create_index(
        "ix_device_commands_device_type", "device_commands", ["device_id", "type"]
    )


def downgrade() -> None:
    """Drop device_commands table."""
    op.drop_index("ix_device_commands_device_type", table_name="device_commands")
    op.drop_index(op.f("ix_device_commands_type"), table_name="device_commands")
    op.drop_index(op.f("ix_device_commands_device_id"), table_name="device_commands")
    op.drop_table("device_commands")
    op.execute("DROP TYPE IF EXISTS commandtype")


