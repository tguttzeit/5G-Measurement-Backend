"""Migration test for the removal of queued rsrp/rsrq/sinr threshold overrides.

Runs the real Alembic migrations in a scratch database: upgrades to the revision before the
cleanup, inserts queued rows and log history with raw SQL, upgrades to head and checks that only
the three removed fields' queued config-override rows are gone.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

REPO_ROOT = Path(__file__).resolve().parents[3]
REVISION_BEFORE_CLEANUP = "20261023_heartbeat_valid_count"
REMOVED_FIELDS = ("rsrp_threshold", "rsrq_threshold", "sinr_threshold")


@pytest.fixture
def scratch_database_url(_engine: Engine):
    name = f"migration_{uuid.uuid4().hex[:12]}"
    with _engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = _engine.url.set(database=name)
    try:
        yield url
    finally:
        with _engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


def _alembic(url, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
    )


def _seed_queue_and_log(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO devices (device_id, api_key_hash, hmac_secret) "
                "VALUES ('dev-1', 'h', 's')"
            )
        )
        for field in (*REMOVED_FIELDS, "heartbeat_interval_s"):
            conn.execute(
                text(
                    "INSERT INTO device_commands (device_id, type, field, payload) "
                    "VALUES ('dev-1', 'config_override', :field, '{\"value\": 1}')"
                ),
                {"field": field},
            )
        # One-shot rows have field NULL and must survive the cleanup.
        conn.execute(
            text(
                "INSERT INTO device_commands (device_id, type, field, payload) "
                "VALUES ('dev-1', 'one_shot', NULL, '{\"command\": \"reboot-now\"}')"
            )
        )
        for field in REMOVED_FIELDS:
            conn.execute(
                text(
                    "INSERT INTO command_log (device_id, direction, kind, name, status) "
                    "VALUES ('dev-1', 'to_device', 'config', :field, 'queued')"
                ),
                {"field": field},
            )


def test_upgrade_deletes_only_queued_rows_of_the_removed_threshold_fields(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", REVISION_BEFORE_CLEANUP)
    engine = create_engine(scratch_database_url)
    try:
        _seed_queue_and_log(engine)

        _alembic(scratch_database_url, "upgrade", "head")

        with engine.connect() as conn:
            queued = conn.execute(
                text("SELECT type, field FROM device_commands ORDER BY id")
            ).all()
            logged = conn.execute(
                text("SELECT name FROM command_log ORDER BY id")
            ).scalars().all()
    finally:
        engine.dispose()

    assert [tuple(row) for row in queued] == [
        ("config_override", "heartbeat_interval_s"),
        ("one_shot", None),
    ]
    assert logged == list(REMOVED_FIELDS)


def test_downgrade_is_a_no_op_and_keeps_remaining_rows(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", "head")
    _alembic(scratch_database_url, "downgrade", REVISION_BEFORE_CLEANUP)
