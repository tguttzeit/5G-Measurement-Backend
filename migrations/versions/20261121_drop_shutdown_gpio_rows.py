"""Delete queued config overrides of the removed system_shutdown_gpio field.

Revision ID: 20261121_drop_shutdown_gpio_rows
Revises: 20261120_run_trash
Create Date: 2026-11-21 12:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261121_drop_shutdown_gpio_rows"
down_revision: str | None = "20261120_run_trash"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # The field is no longer delivered, so its queued rows would only show up as stale
    # entries. command_log keeps the history.
    op.execute(
        "DELETE FROM device_commands WHERE type = 'config_override' "
        "AND field = 'system_shutdown_gpio'"
    )
    op.execute(
        "DELETE FROM user_favorite_config_fields WHERE field_key = 'system_shutdown_gpio'"
    )


def downgrade() -> None:
    # Deleted queue rows cannot be recovered.
    pass
