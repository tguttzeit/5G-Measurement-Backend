"""Integration tests for the measurement data upload endpoint.

Full round trip against a real Postgres (tests/integration/conftest.py) - registers a real
device (mirroring scripts/register_device.py) and posts against POST /measurements (no /api
prefix - see app/routers/measurements.py: that segment is stripped by the Vite dev proxy / Caddy
in front of the app, and TestClient talks to the app directly), covering what
tests/unit/test_measurements.py can only assert without a database: successful persistence, the
flattened-column mapping, per-datapoint device_id cross-checking, and
duplicate submissions (no dedup by design: there is no partial-write race to
detect).
"""
import hashlib
import secrets

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device
from app.models.measurement import Measurement
from app.models.run import Run

MEASUREMENTS_URL = "/measurements"

KNOWN_DEVICE_ID = "measurements-test-device-01"
KNOWN_DEVICE_KEY = "correct-horse-battery-staple"
DEVICE_HEADERS = {"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": KNOWN_DEVICE_KEY}

VALID_DATAPOINT = {
    "timestamp": "2026-07-30T12:00:00.000000Z",
    "device_id": KNOWN_DEVICE_ID,
    "mission_type": "ground",
    "fix": {
        "position": {"latitude": 52.5, "longitude": 13.4, "altitude": 34.2},
        "num_satellites": 8,
        "placeholder": False,
    },
    "cell_sample": {
        "rat": "LTE",
        "mcc": 262,
        "mnc": 1,
        "cell_id": 12345,
        "pci": 100,
        "tac": 5000,
        "rsrp": -95.0,
        "rsrq": -10.0,
        "rssi": -70.0,
        "sinr": 12.0,
        "band": 3,
        "channel": 1500,
        "vendor_specific_extras": None,
    },
}


def _register_device(db_session: Session, device_id: str = KNOWN_DEVICE_ID) -> Device:
    device = Device(
        device_id=device_id,
        api_key_hash=hashlib.sha256(KNOWN_DEVICE_KEY.encode()).hexdigest(),
        hmac_secret=secrets.token_hex(32),
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return device


# --- Auth boundary --------------------------------------------------------


def test_upload_requires_device_id_header(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(
        MEASUREMENTS_URL, json=[VALID_DATAPOINT], headers={"X-Device-Key": KNOWN_DEVICE_KEY}
    )

    assert response.status_code == 401


def test_upload_requires_device_key_header(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(
        MEASUREMENTS_URL, json=[VALID_DATAPOINT], headers={"X-Device-ID": KNOWN_DEVICE_ID}
    )

    assert response.status_code == 401


def test_upload_rejects_wrong_device_key(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(
        MEASUREMENTS_URL,
        json=[VALID_DATAPOINT],
        headers={"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": "wrong-key"},
    )

    assert response.status_code == 401


def test_upload_rejects_unknown_device(test_client: TestClient, db_session: Session):
    response = test_client.post(MEASUREMENTS_URL, json=[VALID_DATAPOINT], headers=DEVICE_HEADERS)

    assert response.status_code == 401


# --- Valid data -------------------------------------------------------


def test_valid_upload_persists_flattened_and_raw_fields(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    response = test_client.post(MEASUREMENTS_URL, json=[VALID_DATAPOINT], headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "success", "count": 1, "device_id": KNOWN_DEVICE_ID}

    stored = db_session.scalars(
        select(Measurement).where(Measurement.device_id == KNOWN_DEVICE_ID)
    ).all()
    assert len(stored) == 1
    measurement = stored[0]
    assert db_session.get(Run, measurement.run_pk).mission_type == "ground"
    assert measurement.latitude == 52.5
    assert measurement.longitude == 13.4
    assert measurement.placeholder is False
    assert measurement.rsrp == -95.0
    assert measurement.rsrq == -10.0
    assert measurement.sinr == 12.0
    assert measurement.rat == "LTE"
    assert measurement.raw_data["cell_sample"]["vendor_specific_extras"] is None


def test_valid_upload_inserts_all_datapoints_in_one_request(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    second_datapoint = {
        **VALID_DATAPOINT,
        "timestamp": "2026-07-30T12:05:00.000000Z",
        "mission_type": "drone",
    }

    response = test_client.post(
        MEASUREMENTS_URL, json=[VALID_DATAPOINT, second_datapoint], headers=DEVICE_HEADERS
    )

    assert response.status_code == 200, response.text
    assert response.json()["count"] == 2
    stored = db_session.scalars(
        select(Measurement).where(Measurement.device_id == KNOWN_DEVICE_ID)
    ).all()
    assert len(stored) == 2


def test_placeholder_fix_is_persisted_and_flagged(test_client: TestClient, db_session: Session):
    _register_device(db_session)
    placeholder_datapoint = {
        **VALID_DATAPOINT,
        "fix": {**VALID_DATAPOINT["fix"], "placeholder": True},
    }

    response = test_client.post(
        MEASUREMENTS_URL, json=[placeholder_datapoint], headers=DEVICE_HEADERS
    )

    assert response.status_code == 200, response.text
    stored = db_session.scalars(
        select(Measurement).where(Measurement.device_id == KNOWN_DEVICE_ID)
    ).one()
    assert stored.placeholder is True


# --- Invalid data -------------------------------------------------------


def test_upload_rejects_missing_required_field(test_client: TestClient, db_session: Session):
    _register_device(db_session)
    malformed = {k: v for k, v in VALID_DATAPOINT.items() if k != "cell_sample"}

    response = test_client.post(MEASUREMENTS_URL, json=[malformed], headers=DEVICE_HEADERS)

    assert response.status_code == 422


def test_upload_rejects_malformed_body(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(
        MEASUREMENTS_URL, json=[{"not": "a valid datapoint"}], headers=DEVICE_HEADERS
    )

    assert response.status_code == 422


def test_upload_rejects_datapoint_device_id_mismatch(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    mismatched = {**VALID_DATAPOINT, "device_id": "some-other-device"}

    response = test_client.post(MEASUREMENTS_URL, json=[mismatched], headers=DEVICE_HEADERS)

    assert response.status_code == 403
    stored = db_session.scalars(select(Measurement)).all()
    assert stored == []


# --- Duplicate data -------------------------------------------------------


def test_duplicate_upload_is_not_deduplicated(test_client: TestClient, db_session: Session):
    """There's no filesystem staging area or dedup - each accepted request
    is its own transaction, so submitting the same datapoint twice yields two rows.
    """
    _register_device(db_session)

    first = test_client.post(MEASUREMENTS_URL, json=[VALID_DATAPOINT], headers=DEVICE_HEADERS)
    second = test_client.post(MEASUREMENTS_URL, json=[VALID_DATAPOINT], headers=DEVICE_HEADERS)

    assert first.status_code == 200
    assert second.status_code == 200
    stored = db_session.scalars(
        select(Measurement).where(Measurement.device_id == KNOWN_DEVICE_ID)
    ).all()
    assert len(stored) == 2
