"""Tests for latency test result ingestion.

Target: POST /api/latency-results, authenticated the same way as heartbeat (X-Device-ID /
X-Device-Key), matching `measurement_software.core.latency_result.LatencyResult` exactly:

    test_type: LatencyTestType
    flent_test: str
    device_id: str
    mission_type: str
    start_timestamp: str
    end_timestamp: str
    start_fix: GNSSFix
    end_fix: GNSSFix
    baseline_rtt_ms: float | None
    rtt_under_load_ms: float | None
    rtt_p99_ms: float | None
    download_mbits_s: float | None
    upload_mbits_s: float | None

The dataclass declares every RTT/throughput field as independently `float | None` with no
`__post_init__` (or other) validation tying them to `test_type` — so this suite does NOT enforce a
cross-field "baseline needs X, under_load needs Y" rule. Inventing a stricter backend rule than
the device itself enforces would reject legitimate payloads we can't yet anticipate.

The tests that exercise successful inserts, payload validation, and the payload/auth device_id
mismatch all authenticate as a real, persisted device (auth is checked before the body is
parsed - see app/device_auth.py - so an unknown device_id 401s before validation ever runs).
`seeded_device` below inserts and tears down that device directly against the configured
database, the same way `scripts/register_device.py` does, so these run as ordinary tests
against whatever Postgres `DATABASE_URL` points at.
"""
import hashlib
import secrets
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.main import app
from app.models import Device
from app.models.latency import LatencyTestResult

client = TestClient(app)

LATENCY_URL = "/latency-results"

KNOWN_DEVICE_ID = "latency-test-device-01"
KNOWN_DEVICE_KEY = "correct-horse-battery-staple"
VALID_HEADERS = {"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": KNOWN_DEVICE_KEY}


@pytest.fixture(autouse=True)
def seeded_device() -> Generator[None, None, None]:
    """Insert the device these tests authenticate as, then remove it afterward.

    Deleting the device cascades to any latency_results rows it owns (the FK is declared
    ondelete="CASCADE"), so no separate cleanup of inserted rows is needed.
    """
    session: Session = SessionLocal()
    try:
        session.merge(
            Device(
                device_id=KNOWN_DEVICE_ID,
                api_key_hash=hashlib.sha256(KNOWN_DEVICE_KEY.encode()).hexdigest(),
                hmac_secret=secrets.token_hex(32),
            )
        )
        session.commit()
    finally:
        session.close()

    yield

    session = SessionLocal()
    try:
        device = session.get(Device, KNOWN_DEVICE_ID)
        if device is not None:
            session.delete(device)
            session.commit()
    finally:
        session.close()


# Matches app.schemas.datapoint.GNSSFix/Position exactly
# (Position.latitude/.longitude, GNSSFix.position/.num_satellites/.placeholder).
SAMPLE_FIX = {
    "position": {"latitude": 52.5, "longitude": 13.4},
    "num_satellites": 8,
    "placeholder": False,
}


def valid_latency_payload(test_type: str = "baseline", **overrides) -> dict:
    payload = {
        "test_type": test_type,
        "flent_test": "tcp_nup",
        "device_id": KNOWN_DEVICE_ID,
        "mission_type": "ground",
        "start_timestamp": "2026-07-30T12:00:00Z",
        "end_timestamp": "2026-07-30T12:00:05Z",
        "start_fix": SAMPLE_FIX,
        "end_fix": SAMPLE_FIX,
        "baseline_rtt_ms": 42.0,
        "rtt_under_load_ms": None,
        "rtt_p99_ms": None,
        "download_mbits_s": None,
        "upload_mbits_s": None,
    }
    payload.update(overrides)
    return payload


def test_valid_baseline_payload_is_accepted():
    payload = valid_latency_payload("baseline")
    response = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert response.status_code == 201


def test_valid_under_load_payload_is_accepted():
    response = client.post(
        LATENCY_URL,
        json=valid_latency_payload(
            "under_load",
            baseline_rtt_ms=None,
            rtt_under_load_ms=58.3,
            rtt_p99_ms=91.2,
            download_mbits_s=120.5,
            upload_mbits_s=15.2,
        ),
        headers=VALID_HEADERS,
    )

    assert response.status_code == 201


def test_rtt_and_throughput_fields_are_all_independently_nullable():
    """No cross-field requiredness rule: mirrors LatencyResult's own lack of one."""
    payload = valid_latency_payload(
        "baseline",
        baseline_rtt_ms=None,
        rtt_under_load_ms=None,
        rtt_p99_ms=None,
        download_mbits_s=None,
        upload_mbits_s=None,
    )

    response = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert response.status_code == 201


def test_invalid_test_type_rejected_with_422():
    response = client.post(
        LATENCY_URL, json=valid_latency_payload(test_type="not-a-real-type"), headers=VALID_HEADERS
    )

    assert response.status_code == 422


def test_flent_test_field_is_required():
    payload = valid_latency_payload()
    del payload["flent_test"]

    response = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert response.status_code == 422


def test_start_fix_and_end_fix_use_nested_position_not_flat_lat_lon():
    """Regression guard: a flat {"lat": .., "lon": ..} fix must be rejected."""
    payload = valid_latency_payload(start_fix={"lat": 52.5, "lon": 13.4, "num_satellites": 8})

    response = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert response.status_code == 422


@pytest.mark.parametrize("field", ["flent_test", "device_id", "mission_type"])
def test_oversized_string_field_returns_422(field):
    # 255 matches the max_length of Datapoint's own device_id/mission_type fields
    # (app/schemas/datapoint.py).
    payload = valid_latency_payload(**{field: "x" * 256})

    response = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert response.status_code == 422


def test_missing_credentials_returns_401_not_422():
    response = client.post(LATENCY_URL, json=valid_latency_payload())

    assert response.status_code == 401


def test_wrong_device_key_returns_401():
    response = client.post(
        LATENCY_URL,
        json=valid_latency_payload(),
        headers={"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": "wrong-key"},
    )

    assert response.status_code == 401


def test_payload_device_id_mismatch_returns_403():
    payload = valid_latency_payload(device_id="some-other-device")

    response = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert response.status_code == 403


# --- Batch upload ---------------------------------------------


def _stored_rows() -> list[LatencyTestResult]:
    session: Session = SessionLocal()
    try:
        return list(
            session.scalars(
                select(LatencyTestResult).where(LatencyTestResult.device_id == KNOWN_DEVICE_ID)
            )
        )
    finally:
        session.close()


def test_array_payload_is_accepted_and_inserts_all_rows():
    payload = [valid_latency_payload("baseline"), valid_latency_payload("under_load")]

    response = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert response.status_code == 201, response.text
    assert response.json() == {
        "status": "success",
        "count": 2,
        "device_id": KNOWN_DEVICE_ID,
    }
    assert len(_stored_rows()) == 2


def test_empty_array_payload_is_accepted_and_inserts_nothing():
    response = client.post(LATENCY_URL, json=[], headers=VALID_HEADERS)

    assert response.status_code == 201
    assert response.json()["count"] == 0
    assert _stored_rows() == []


def test_array_payload_checks_every_item_device_id_not_just_the_first():
    """A batch endpoint that only validated one item while trusting the rest would let an
    authenticated device smuggle another device's data into the batch."""
    payload = [
        valid_latency_payload("baseline"),
        valid_latency_payload("under_load", device_id="some-other-device"),
    ]

    response = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert response.status_code == 403
    assert _stored_rows() == []


def test_array_payload_rejects_malformed_item_with_422():
    payload = [valid_latency_payload("baseline"), {"not": "a valid latency result"}]

    response = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert response.status_code == 422
    assert _stored_rows() == []


# --- Idempotency key dedup -------------------------------------


def test_duplicate_idempotency_key_is_not_inserted_twice():
    payload = valid_latency_payload("baseline", idempotency_key="capture-uuid-1")

    first = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)
    second = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert first.status_code == 201
    assert second.status_code == 201
    assert len(_stored_rows()) == 1


def test_missing_idempotency_key_keeps_duplicate_submissions_allowed():
    """No key at all means no dedup is attempted - matches /api/measurements's existing
    no-dedup-by-default behavior."""
    payload = valid_latency_payload("baseline")

    first = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)
    second = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert first.status_code == 201
    assert second.status_code == 201
    assert len(_stored_rows()) == 2


def test_duplicate_idempotency_key_within_same_batch_is_deduped():
    payload = [
        valid_latency_payload("baseline", idempotency_key="capture-uuid-2"),
        valid_latency_payload("under_load", idempotency_key="capture-uuid-2"),
    ]

    response = client.post(LATENCY_URL, json=payload, headers=VALID_HEADERS)

    assert response.status_code == 201
    assert response.json()["count"] == 2
    assert len(_stored_rows()) == 1


def test_different_devices_can_reuse_the_same_idempotency_key():
    other_device_id = "latency-test-device-02"
    session: Session = SessionLocal()
    try:
        session.merge(
            Device(
                device_id=other_device_id,
                api_key_hash=hashlib.sha256(KNOWN_DEVICE_KEY.encode()).hexdigest(),
                hmac_secret=secrets.token_hex(32),
            )
        )
        session.commit()
    finally:
        session.close()

    try:
        shared_key = "capture-uuid-shared"
        first = client.post(
            LATENCY_URL,
            json=valid_latency_payload("baseline", idempotency_key=shared_key),
            headers=VALID_HEADERS,
        )
        second = client.post(
            LATENCY_URL,
            json=valid_latency_payload(
                "baseline", device_id=other_device_id, idempotency_key=shared_key
            ),
            headers={"X-Device-ID": other_device_id, "X-Device-Key": KNOWN_DEVICE_KEY},
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert len(_stored_rows()) == 1
    finally:
        session = SessionLocal()
        try:
            device = session.get(Device, other_device_id)
            if device is not None:
                session.delete(device)
                session.commit()
        finally:
            session.close()
