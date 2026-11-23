"""Migration test for normalizing the run data model.

Runs the real Alembic migrations in a scratch database: upgrades to the revision before the
normalization, inserts measurements and latency results with raw SQL, upgrades to head and checks
that every row points at its run, that the run took over the mission type, and that the
duplicated columns are gone without losing a row.
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
REVISION_BEFORE_NORMALIZATION = "20261023_drop_threshold_rows"


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


def _insert_measurement(conn, device_id: str, run_id: str, mission_type: str, timestamp: str):
    conn.execute(
        text(
            "INSERT INTO measurements (timestamp, device_id, mission_type, run_id, placeholder, "
            "raw_data) VALUES (:timestamp, :device_id, :mission_type, :run_id, false, '{}')"
        ),
        {
            "timestamp": timestamp,
            "device_id": device_id,
            "mission_type": mission_type,
            "run_id": run_id,
        },
    )


def _insert_latency_result(conn, device_id: str, run_id: str, mission_type: str, key: str):
    conn.execute(
        text(
            "INSERT INTO latency_results (device_id, test_type, flent_test, mission_type, "
            "run_id, start_timestamp, end_timestamp, start_fix, end_fix, idempotency_key) "
            "VALUES (:device_id, 'baseline', 'ping', :mission_type, :run_id, "
            "'2026-08-10 10:00:00+00', '2026-08-10 10:01:00+00', '{}', '{}', :key)"
        ),
        {"device_id": device_id, "run_id": run_id, "mission_type": mission_type, "key": key},
    )


def _seed(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO devices (device_id, api_key_hash, hmac_secret) "
                "VALUES ('dev-1', 'x', 'y')"
            )
        )
        conn.execute(text("INSERT INTO campaigns (name) VALUES ('august')"))
        _insert_measurement(conn, "dev-1", "run-a", "drone", "2026-08-10 10:00:00+00")
        _insert_measurement(conn, "dev-1", "run-a", "drone", "2026-08-10 10:05:00+00")
        _insert_measurement(conn, "dev-2", "run-a", "ground", "2026-08-10 11:00:00+00")
        _insert_measurement(conn, "dev-1", "run-b", "ground", "2026-08-11 11:00:00+00")
        # the state the runs table migration leaves behind: a runs row per measurement run,
        # none for latency-only runs
        conn.execute(
            text(
                "INSERT INTO runs (device_id, run_id) "
                "SELECT DISTINCT device_id, run_id FROM measurements"
            )
        )
        conn.execute(
            text("UPDATE runs SET campaign_id = (SELECT id FROM campaigns) WHERE run_id = 'run-b'")
        )
        _insert_latency_result(conn, "dev-1", "run-a", "drone", "k1")
        _insert_latency_result(conn, "dev-1", "run-latency-only", "ground", "k2")


@pytest.fixture
def migrated_engine(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", REVISION_BEFORE_NORMALIZATION)
    engine = create_engine(scratch_database_url)
    try:
        _seed(engine)
        _alembic(scratch_database_url, "upgrade", "head")
        yield engine
    finally:
        engine.dispose()


def _rows(engine: Engine, sql: str) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql))]


def test_every_measurement_points_at_the_run_of_its_device_and_run_id(migrated_engine):
    rows = _rows(
        migrated_engine,
        "SELECT runs.device_id, runs.run_id, count(*) FROM measurements "
        "JOIN runs ON runs.id = measurements.run_pk GROUP BY 1, 2 ORDER BY 1, 2",
    )

    assert rows == [("dev-1", "run-a", 2), ("dev-1", "run-b", 1), ("dev-2", "run-a", 1)]


def test_every_latency_result_points_at_a_run_even_without_measurements(migrated_engine):
    rows = _rows(
        migrated_engine,
        "SELECT runs.device_id, runs.run_id FROM latency_results "
        "JOIN runs ON runs.id = latency_results.run_pk ORDER BY 2",
    )

    assert rows == [("dev-1", "run-a"), ("dev-1", "run-latency-only")]


def test_runs_take_over_the_mission_type_of_their_rows(migrated_engine):
    rows = _rows(
        migrated_engine, "SELECT device_id, run_id, mission_type FROM runs ORDER BY 1, 2"
    )

    assert rows == [
        ("dev-1", "run-a", "drone"),
        ("dev-1", "run-b", "ground"),
        ("dev-1", "run-latency-only", "ground"),
        ("dev-2", "run-a", "ground"),
    ]


def test_existing_campaign_assignments_and_names_survive(migrated_engine):
    rows = _rows(
        migrated_engine,
        "SELECT run_id, name, campaign_id IS NOT NULL FROM runs WHERE device_id = 'dev-1' "
        "AND run_id IN ('run-a', 'run-b') ORDER BY 1",
    )

    assert rows == [("run-a", None, False), ("run-b", None, True)]


def test_redundant_columns_are_dropped_and_no_row_is_lost(migrated_engine):
    measurement_columns = {
        name
        for (name,) in _rows(
            migrated_engine,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'measurements'",
        )
    }
    latency_columns = {
        name
        for (name,) in _rows(
            migrated_engine,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'latency_results'",
        )
    }

    assert "run_id" not in measurement_columns | latency_columns
    assert "mission_type" not in measurement_columns | latency_columns
    assert {"run_pk", "device_id"} <= measurement_columns
    assert {"run_pk", "device_id"} <= latency_columns
    assert _rows(migrated_engine, "SELECT count(*) FROM measurements") == [(4,)]
    assert _rows(migrated_engine, "SELECT count(*) FROM latency_results") == [(2,)]


def test_deleting_a_run_cascades_to_its_rows_only(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text("DELETE FROM runs WHERE device_id = 'dev-1' AND run_id = 'run-a'"))

    assert _rows(
        migrated_engine,
        "SELECT runs.device_id, runs.run_id FROM measurements "
        "JOIN runs ON runs.id = measurements.run_pk ORDER BY 1, 2",
    ) == [("dev-1", "run-b"), ("dev-2", "run-a")]
    assert _rows(migrated_engine, "SELECT count(*) FROM latency_results") == [(1,)]


def test_downgrade_restores_the_duplicated_columns(scratch_database_url):
    _alembic(scratch_database_url, "upgrade", REVISION_BEFORE_NORMALIZATION)
    engine = create_engine(scratch_database_url)
    try:
        _seed(engine)
        _alembic(scratch_database_url, "upgrade", "head")
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE runs SET mission_type = 'ground' WHERE run_id = 'run-a'")
            )

        _alembic(scratch_database_url, "downgrade", REVISION_BEFORE_NORMALIZATION)

        assert _rows(
            engine,
            "SELECT device_id, run_id, mission_type FROM measurements ORDER BY 1, 2, 3",
        ) == [
            ("dev-1", "run-a", "ground"),
            ("dev-1", "run-a", "ground"),
            ("dev-1", "run-b", "ground"),
            ("dev-2", "run-a", "ground"),
        ]
        assert _rows(
            engine, "SELECT run_id FROM latency_results ORDER BY 1"
        ) == [("run-a",), ("run-latency-only",)]
    finally:
        engine.dispose()
