"""Migration test for the correction of NR5G samples stored with the old AT+QENG column layout.

Older firmware parsed NR5G-NSA and NR5G-SA servingcell lines with one shared layout, which put
fields into the wrong keys. Runs the real Alembic migrations in a scratch database: upgrades to
the revision before the correction, inserts measurements with raw SQL, upgrades to head and
checks that only rows in the old layout were rewritten.
"""
import json
import os
import subprocess
import sys

from sqlalchemy import create_engine, text

from tests.integration.test_api.test_threshold_override_cleanup_migration import (
    REPO_ROOT,
    scratch_database_url,  # noqa: F401 - pytest fixture
)

REVISION_BEFORE_CORRECTION = "20261122_rename_waiting_mode"


def _alembic(url, *args: str) -> str:
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stderr


def _cell_sample(rat: str, **fields) -> dict:
    sample = {
        "rat": rat,
        "mcc": None,
        "mnc": None,
        "cell_id": None,
        "pci": None,
        "tac": None,
        "rsrp": None,
        "rsrq": None,
        "rssi": None,
        "sinr": None,
        "band": None,
        "channel": None,
        "vendor_specific_extras": None,
    }
    return {**sample, **fields}


# "NR5G-NSA",262,02,797,-103,21,-13,631968,78,10,1 as the old parser stored it: the PCI in `tac`,
# the DL bandwidth index in `scs_index`.
OLD_NSA = _cell_sample(
    "NR5G-NSA",
    mcc=262,
    mnc=2,
    tac=797,
    rsrp=-103.0,
    sinr=21.0,
    rsrq=-13.0,
    channel=631968,
    band=78,
    vendor_specific_extras={"scs_index": 10},
)
# duplex,MCC,MNC,cellID,PCID,TAC,ARFCN,band,NR_DL_bandwidth,RSRP,... shifted by one column: MCC in
# `mnc`, MNC in `tac`, cell id in `rsrp`, PCI in `sinr`, TAC in `rsrq`.
OLD_SA = _cell_sample(
    "NR5G-SA",
    mnc=262,
    tac=1,
    rsrp=1715004.0,
    sinr=500.0,
    rsrq=None,
    channel=627264,
    band=78,
    vendor_specific_extras={"scs_index": 12},
)
QSCAN_SA = _cell_sample(
    "NR5G-SA", mcc=262, mnc=1, pci=500, rsrp=-95.0, rsrq=-11.0, sinr=15.0, band=78
)
LTE = _cell_sample(
    "LTE", mcc=262, mnc=1, cell_id=12345, pci=100, tac=5000, rsrp=-95.0, rsrq=-10.0, sinr=12.0
)
NEW_NSA = _cell_sample(
    "NR5G-NSA",
    mcc=262,
    mnc=2,
    pci=797,
    rsrp=-103.0,
    sinr=21.0,
    rsrq=-13.0,
    vendor_specific_extras={"dl_bandwidth_index": 10, "scs_index": 1},
)


def _insert_measurement(conn, run_pk: int, cell_sample: dict) -> None:
    raw_data = {
        "timestamp": "2026-11-01T12:00:00Z",
        "device_id": "dev-1",
        "mission_type": "ground",
        "fix": {"position": {"latitude": 48.0, "longitude": 10.0}, "num_satellites": 8},
        "cell_sample": cell_sample,
    }
    conn.execute(
        text(
            "INSERT INTO measurements (timestamp, device_id, run_pk, latitude, longitude, "
            "placeholder, rsrp, rsrq, sinr, rat, raw_data) "
            "VALUES ('2026-11-01T12:00:00Z', 'dev-1', :run_pk, 48.0, 10.0, false, "
            ":rsrp, :rsrq, :sinr, :rat, CAST(:raw_data AS jsonb))"
        ),
        {
            "run_pk": run_pk,
            "rsrp": cell_sample["rsrp"],
            "rsrq": cell_sample["rsrq"],
            "sinr": cell_sample["sinr"],
            "rat": cell_sample["rat"],
            "raw_data": json.dumps(raw_data),
        },
    )


def _stored(engine) -> list[tuple]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT rsrp, rsrq, sinr, raw_data->'cell_sample' FROM measurements ORDER BY id")
        ).all()
    return [tuple(row) for row in rows]


def test_upgrade_corrects_only_samples_in_the_old_layout(scratch_database_url):  # noqa: F811
    _alembic(scratch_database_url, "upgrade", REVISION_BEFORE_CORRECTION)
    engine = create_engine(scratch_database_url)
    try:
        with engine.begin() as conn:
            run_pk = conn.execute(
                text(
                    "INSERT INTO runs (device_id, run_id, mission_type) "
                    "VALUES ('dev-1', 'run-1', 'ground') RETURNING id"
                )
            ).scalar_one()
            for sample in (OLD_NSA, OLD_SA, QSCAN_SA, LTE, NEW_NSA):
                _insert_measurement(conn, run_pk, sample)

        output = _alembic(scratch_database_url, "upgrade", "head")
        corrected = _stored(engine)

        # Downgrading is a no-op, and a second run finds nothing left in the old layout.
        _alembic(scratch_database_url, "downgrade", REVISION_BEFORE_CORRECTION)
        output_again = _alembic(scratch_database_url, "upgrade", "head")
        corrected_again = _stored(engine)
    finally:
        engine.dispose()

    assert corrected == [
        (
            -103.0,
            -13.0,
            21.0,
            {
                **OLD_NSA,
                "pci": 797,
                "tac": None,
                "vendor_specific_extras": {"dl_bandwidth_index": 10, "scs_index": None},
            },
        ),
        (
            None,
            None,
            None,
            {
                **OLD_SA,
                "mcc": 262,
                "mnc": 1,
                "pci": 500,
                "tac": None,
                "cell_id": None,
                "rsrp": None,
                "rsrq": None,
                "sinr": None,
                "vendor_specific_extras": {
                    "dl_bandwidth_index": 12,
                    "scs_index": None,
                    "legacy_layout_signal_lost": True,
                },
            },
        ),
        (-95.0, -11.0, 15.0, QSCAN_SA),
        (-95.0, -10.0, 12.0, LTE),
        (-103.0, -13.0, 21.0, NEW_NSA),
    ]
    assert "1 NR5G-NSA and 1 NR5G-SA" in output
    assert corrected_again == corrected
    assert "0 NR5G-NSA and 0 NR5G-SA" in output_again
