"""Migration test for the run trash columns.

Runs the real Alembic migrations in a scratch database: existing runs must come out of the
upgrade active (not in the trash), and the downgrade must drop both columns again.
"""
from sqlalchemy import create_engine, inspect, text

from tests.integration.test_api.test_threshold_override_cleanup_migration import (
    _alembic,
    scratch_database_url,  # noqa: F401 - pytest fixture
)

REVISION_BEFORE_TRASH = "20261030_user_notif_settings"


def test_existing_runs_stay_active_and_the_downgrade_drops_the_columns(scratch_database_url):  # noqa: F811
    _alembic(scratch_database_url, "upgrade", REVISION_BEFORE_TRASH)
    engine = create_engine(scratch_database_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO runs (device_id, run_id, mission_type) "
                    "VALUES ('dev-1', 'run-1', 'ground')"
                )
            )

        _alembic(scratch_database_url, "upgrade", "head")
        with engine.connect() as conn:
            row = conn.execute(text("SELECT deleted_at, deleted_by FROM runs")).one()
        assert tuple(row) == (None, None)

        _alembic(scratch_database_url, "downgrade", REVISION_BEFORE_TRASH)
        columns = {column["name"] for column in inspect(engine).get_columns("runs")}
        assert not columns & {"deleted_at", "deleted_by"}
    finally:
        engine.dispose()
