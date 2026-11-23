"""Rename the stored legacy Waiting Mode values to their Manual Mode names.

Revision ID: 20261122_rename_waiting_mode
Revises: 20261121_drop_shutdown_gpio_rows
Create Date: 2026-11-22 12:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261122_rename_waiting_mode"
down_revision: str | None = "20261121_drop_shutdown_gpio_rows"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # The strict RunPhase enum no longer knows `waiting_mode_idle`, and the reported mode no
    # longer maps `waiting`, so stored heartbeats must carry the new names to keep rendering.
    op.execute(
        "UPDATE heartbeats SET run_phase = 'manual_mode_idle' WHERE run_phase = 'waiting_mode_idle'"
    )
    op.execute(
        """
        UPDATE heartbeats
        SET current_config = (
            current_config::jsonb
            || CASE WHEN current_config::jsonb ->> 'system_mode' = 'waiting'
                    THEN '{"system_mode": "manual"}'::jsonb ELSE '{}'::jsonb END
            || CASE WHEN current_config::jsonb ->> 'mode' = 'waiting'
                    THEN '{"mode": "manual"}'::jsonb ELSE '{}'::jsonb END
        )::json
        WHERE current_config::jsonb ->> 'system_mode' = 'waiting'
           OR current_config::jsonb ->> 'mode' = 'waiting'
        """
    )
    # Commands queued before the switch are still delivered as `mode-waiting-now`; updated
    # devices accept that as an alias, so queued rows and the command log history stay as they are.


def downgrade() -> None:
    # The renamed values cannot be told apart from ones the device reported as manual.
    pass
