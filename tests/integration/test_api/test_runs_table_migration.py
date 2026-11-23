"""Migration test for the `runs` table.

Runs the real Alembic migrations in a scratch database: upgrades to the revision before `runs`
existed, inserts date-range campaigns and measurements with raw SQL, upgrades to head and checks
that every distinct (device_id, run_id) got a row and that campaigns were converted into run
assignments by the run's start day.
"""
import os
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

REPO_ROOT = Path(__file__).resolve().parents[3]
REVISION_BEFORE_RUNS_TABLE = "20261022_add_command_log"


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


def _insert_measurement(conn, device_id: str, run_id: str, timestamp: str) -> None:
    conn.execute(
        text(
            "INSERT INTO measurements (timestamp, device_id, mission_type, run_id, placeholder, "
            "raw_data) VALUES (:timestamp, :device_id, 'ground', :run_id, false, '{}')"
        ),
        {"timestamp": timestamp, "device_id": device_id, "run_id": run_id},
    )


def _seed_date_range_campaigns(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO campaigns (name, start_date, end_date) VALUES "
                "('august', '2026-08-01', '2026-08-31'),"
                " ('overlap', '2026-08-15', '2026-09-15'),"
                " ('empty', '2027-01-01', '2027-01-31')"
            )
        )
        # two points in one run, the second one past the end of the campaign range
        _insert_measurement(conn, "dev-1", "run-in-august", "2026-08-10 10:00:00+00")
        _insert_measurement(conn, "dev-1", "run-in-august", "2026-09-02 10:00:00+00")
        # starts 22:00 UTC on Aug 31st: belongs to the campaign by its UTC start day
        _insert_measurement(conn, "dev-1", "run-late-on-last-day", "2026-08-31 22:00:00+00")
        # the first matching campaign wins where ranges overlap
        _insert_measurement(conn, "dev-2", "run-in-overlap", "2026-08-20 09:00:00+00")
        _insert_measurement(conn, "dev-2", "run-in-overlap", "2026-08-20 09:30:00+00")
        # after every campaign, and before every campaign
        _insert_measurement(conn, "dev-1", "run-in-september", "2026-09-10 09:00:00+00")
        _insert_measurement(conn, "dev-1", "run-outside", "2026-12-01 09:00:00+00")
        _insert_measurement(conn, "dev-1", "run-before", "2026-01-01 09:00:00+00")
        # same run_id on another device is a different run
        _insert_measurement(conn, "dev-2", "run-in-august", "2026-12-01 09:00:00+00")


def _run_campaigns(engine: Engine) -> dict[tuple[str, str], str | None]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT runs.device_id, runs.run_id, campaigns.name FROM runs "
                "LEFT JOIN campaigns ON campaigns.id = runs.campaign_id"
            )
        ).all()
    return {(device_id, run_id): name for device_id, run_id, name in rows}


def test_upgrade_creates_a_run_per_distinct_device_and_run_id(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", REVISION_BEFORE_RUNS_TABLE)
    engine = create_engine(scratch_database_url)
    try:
        _seed_date_range_campaigns(engine)

        _alembic(scratch_database_url, "upgrade", "head")

        assert set(_run_campaigns(engine)) == {
            ("dev-1", "run-in-august"),
            ("dev-1", "run-late-on-last-day"),
            ("dev-2", "run-in-overlap"),
            ("dev-1", "run-in-september"),
            ("dev-1", "run-outside"),
            ("dev-1", "run-before"),
            ("dev-2", "run-in-august"),
        }
    finally:
        engine.dispose()


def test_upgrade_assigns_runs_to_the_campaign_containing_their_start_day(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", REVISION_BEFORE_RUNS_TABLE)
    engine = create_engine(scratch_database_url)
    try:
        _seed_date_range_campaigns(engine)

        _alembic(scratch_database_url, "upgrade", "head")

        assert _run_campaigns(engine) == {
            ("dev-1", "run-in-august"): "august",
            ("dev-1", "run-late-on-last-day"): "august",
            ("dev-2", "run-in-overlap"): "august",
            ("dev-1", "run-in-september"): "overlap",
            ("dev-1", "run-outside"): None,
            ("dev-1", "run-before"): None,
            ("dev-2", "run-in-august"): None,
        }
    finally:
        engine.dispose()


def test_upgrade_drops_the_campaign_date_columns(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", "head")
    engine = create_engine(scratch_database_url)
    try:
        with engine.connect() as conn:
            columns = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'campaigns'"
                )
            ).scalars().all()
    finally:
        engine.dispose()

    assert sorted(columns) == ["id", "name"]


def test_deleting_a_campaign_unassigns_its_runs(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", REVISION_BEFORE_RUNS_TABLE)
    engine = create_engine(scratch_database_url)
    try:
        _seed_date_range_campaigns(engine)
        _alembic(scratch_database_url, "upgrade", "head")

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM campaigns WHERE name = 'august'"))

        assert _run_campaigns(engine)[("dev-1", "run-in-august")] is None
    finally:
        engine.dispose()


def test_downgrade_restores_date_ranges_from_the_assigned_runs(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", REVISION_BEFORE_RUNS_TABLE)
    engine = create_engine(scratch_database_url)
    try:
        _seed_date_range_campaigns(engine)
        _alembic(scratch_database_url, "upgrade", "head")

        _alembic(scratch_database_url, "downgrade", REVISION_BEFORE_RUNS_TABLE)

        with engine.connect() as conn:
            ranges = {
                name: (start, end)
                for name, start, end in conn.execute(
                    text("SELECT name, start_date, end_date FROM campaigns")
                )
            }
            runs_table = conn.execute(text("SELECT to_regclass('runs')")).scalar()
    finally:
        engine.dispose()

    assert runs_table is None
    assert ranges["august"] == (date(2026, 8, 10), date(2026, 9, 2))
    assert ranges["overlap"] == (date(2026, 9, 10), date(2026, 9, 10))
    # a campaign without runs has no period: it falls back to a single placeholder day
    assert ranges["empty"][0] == ranges["empty"][1]
