"""Migration test for the `run_id` backfill.

Runs the real Alembic migrations in a scratch database: upgrades to the revision before
`run_id` existed, inserts legacy rows with raw SQL, upgrades to head and checks the backfilled ids
- including that they equal what the ingest fallback (app.run_ids.legacy_run_id) produces.
"""
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.run_ids import legacy_run_id

REPO_ROOT = Path(__file__).resolve().parents[3]
REVISION_BEFORE_RUN_ID = "20261006_latency_idempotency"


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


def _insert_legacy_rows(engine: Engine) -> None:
    fix = '{"position": {"latitude": 52.5, "longitude": 13.4}, "placeholder": false}'
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO devices (device_id, api_key_hash, hmac_secret) "
                          "VALUES ('dev-1', 'h', 's'), ('dev-2', 'h', 's')"))
        conn.execute(text(
            "INSERT INTO measurements (timestamp, device_id, mission_type, placeholder, raw_data) "
            "VALUES ('2026-07-30 01:00:00+00', 'dev-1', 'ground', false, '{}'),"
            " ('2026-07-30 23:59:00+00', 'dev-1', 'ground', false, '{}'),"
            " ('2026-07-30 23:00:00-05:00', 'dev-1', 'ground', false, '{}'),"
            " ('2026-07-30 12:00:00+00', 'dev-1', 'drone', false, '{}'),"
            " ('2026-07-30 12:00:00+00', 'dev-2', 'ground', false, '{}')"
        ))
        conn.execute(text(
            "INSERT INTO latency_results (device_id, test_type, flent_test, mission_type, "
            "start_timestamp, end_timestamp, start_fix, end_fix) VALUES "
            f"('dev-1', 'baseline', 'ping', 'ground', '2026-07-30 12:00:00+00', "
            f"'2026-07-30 12:01:00+00', '{fix}', '{fix}')"
        ))


def test_backfill_groups_existing_rows_into_one_legacy_run_per_device_mission_and_utc_day(
    scratch_database_url,
):
    _alembic(scratch_database_url, "upgrade", REVISION_BEFORE_RUN_ID)
    engine = create_engine(scratch_database_url)
    try:
        _insert_legacy_rows(engine)

        _alembic(scratch_database_url, "upgrade", "20261013_add_run_id")

        with engine.connect() as conn:
            measurement_ids = conn.execute(
                text("SELECT device_id, mission_type, timestamp, run_id FROM measurements")
            ).all()
            latency_ids = conn.execute(text("SELECT run_id FROM latency_results")).scalars().all()
    finally:
        engine.dispose()

    assert {run_id for *_, run_id in measurement_ids} == {
        "legacy-dev-1-ground-2026-07-30",
        "legacy-dev-1-ground-2026-07-31",  # 23:00 at UTC-05:00 is already the 31st in UTC
        "legacy-dev-1-drone-2026-07-30",
        "legacy-dev-2-ground-2026-07-30",
    }
    for device_id, mission_type, timestamp, run_id in measurement_ids:
        assert run_id == legacy_run_id(device_id, mission_type, timestamp)
    assert latency_ids == [legacy_run_id("dev-1", "ground", datetime(2026, 7, 30, tzinfo=UTC))]


def test_downgrade_drops_the_run_id_columns(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", "head")
    _alembic(scratch_database_url, "downgrade", REVISION_BEFORE_RUN_ID)
    engine = create_engine(scratch_database_url)
    try:
        with engine.connect() as conn:
            columns = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name IN ('measurements', 'latency_results') "
                    "AND column_name = 'run_id'"
                )
            ).all()
    finally:
        engine.dispose()

    assert columns == []
