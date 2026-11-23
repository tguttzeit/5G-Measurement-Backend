"""Migration test for the rename of the stored Waiting Mode values to Manual Mode.

Runs the real Alembic migrations in a scratch database: upgrades to the revision before the
rename, inserts heartbeats with raw SQL, upgrades to head and checks that only the legacy
values were renamed.
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
REVISION_BEFORE_RENAME = "20261121_drop_shutdown_gpio_rows"


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


def _insert_heartbeat(conn, run_phase: str | None, current_config: str | None) -> None:
    conn.execute(
        text(
            "INSERT INTO heartbeats (device_id, datapoints_total, datapoints_valid, "
            "datapoints_invalid, pipeline_broken, storage_pending_files, "
            "storage_disk_free_bytes, run_phase, current_config) "
            "VALUES ('dev-1', 0, 0, 0, false, 0, 0, :run_phase, CAST(:config AS json))"
        ),
        {"run_phase": run_phase, "config": current_config},
    )


def test_upgrade_renames_only_the_legacy_waiting_values(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", REVISION_BEFORE_RENAME)
    engine = create_engine(scratch_database_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO devices (device_id, api_key_hash, hmac_secret) "
                    "VALUES ('dev-1', 'h', 's')"
                )
            )
            legacy_config = '{"system_mode": "waiting", "mode": "waiting", "x": 1}'
            _insert_heartbeat(conn, "waiting_mode_idle", legacy_config)
            _insert_heartbeat(conn, "waiting_for_gps_fix", '{"system_mode": "auto"}')
            _insert_heartbeat(conn, "manual_mode_idle", '{"mode": "waiting"}')
            _insert_heartbeat(conn, None, None)

        _alembic(scratch_database_url, "upgrade", "head")

        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT run_phase, current_config FROM heartbeats ORDER BY id")
            ).all()
    finally:
        engine.dispose()

    assert [tuple(row) for row in rows] == [
        ("manual_mode_idle", {"system_mode": "manual", "mode": "manual", "x": 1}),
        ("waiting_for_gps_fix", {"system_mode": "auto"}),
        ("manual_mode_idle", {"mode": "manual"}),
        (None, None),
    ]


def test_downgrade_is_a_no_op(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", "head")
    _alembic(scratch_database_url, "downgrade", REVISION_BEFORE_RENAME)
