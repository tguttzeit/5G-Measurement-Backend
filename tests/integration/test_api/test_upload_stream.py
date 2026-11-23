"""Integration tests for GET /measurements/stream and the publish in POST /measurements.

A live SSE response never ends, so these subscribe to the broadcaster directly to observe what
the real `POST /measurements` publishes, and use the HTTP layer only for the responses that
terminate (auth, 429). Mirrors tests/integration/test_api/test_heartbeat_stream.py.
"""
import hashlib
import secrets

import pytest
from fastapi_users.password import PasswordHelper

from app.models import Device
from app.models.user import User
from app.upload_events import upload_broadcaster

password_helper = PasswordHelper()

STREAM_URL = "/measurements/stream"
MEASUREMENTS_URL = "/measurements"

DEVICE_ID = "upload-stream-test-device-01"
DEVICE_KEY = "correct-horse-battery-staple"
DEVICE_HEADERS = {"X-Device-ID": DEVICE_ID, "X-Device-Key": DEVICE_KEY}

VALID_DATAPOINT = {
    "timestamp": "2026-07-30T12:00:00.000000Z",
    "device_id": DEVICE_ID,
    "mission_type": "ground",
    "run_id": "11111111-1111-1111-1111-111111111111",
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


def _register_device(db_session) -> None:
    db_session.add(
        Device(
            device_id=DEVICE_ID,
            api_key_hash=hashlib.sha256(DEVICE_KEY.encode()).hexdigest(),
            hmac_secret=secrets.token_hex(32),
        )
    )
    db_session.commit()


def _superuser_headers(db_session, test_client, email: str = "superuser") -> dict:
    user = User(
        email=email,
        hashed_password=password_helper.hash("correct-horse-battery-staple"),
        is_active=True,
        is_superuser=True,
        is_verified=False,
    )
    db_session.add(user)
    db_session.commit()
    response = test_client.post(
        "/auth/login", data={"username": email, "password": "correct-horse-battery-staple"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _regular_user_headers(db_session, test_client, email: str = "regular") -> dict:
    user = User(
        email=email,
        hashed_password=password_helper.hash("correct-horse-battery-staple"),
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )
    db_session.add(user)
    db_session.commit()
    response = test_client.post(
        "/auth/login", data={"username": email, "password": "correct-horse-battery-staple"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _no_leftover_subscribers():
    yield
    assert upload_broadcaster.total_subscribers == 0


def test_stream_requires_auth(test_client):
    response = test_client.get(STREAM_URL)

    assert response.status_code == 401


def test_stream_rejects_non_superuser(db_session, test_client):
    headers = _regular_user_headers(db_session, test_client)

    response = test_client.get(STREAM_URL, headers=headers)

    assert response.status_code == 403


def test_stream_rejects_device_key_auth(db_session, test_client):
    _register_device(db_session)

    response = test_client.get(STREAM_URL, headers=DEVICE_HEADERS)

    assert response.status_code == 401


def test_stream_over_the_per_user_cap_is_429(db_session, test_client):
    headers = _superuser_headers(db_session, test_client)
    user_id = db_session.query(User).one().id
    held = [upload_broadcaster.subscribe(user_id) for _ in range(5)]
    try:
        response = test_client.get(STREAM_URL, headers=headers)
    finally:
        for subscription in held:
            subscription.close()

    assert response.status_code == 429


def test_uploading_measurements_publishes_device_id_and_run_ids(db_session, test_client):
    _register_device(db_session)
    subscription = upload_broadcaster.subscribe(user_id=1)
    try:
        response = test_client.post(
            MEASUREMENTS_URL, json=[VALID_DATAPOINT], headers=DEVICE_HEADERS
        )

        assert response.status_code == 200
        event = subscription.queue.get_nowait()
        assert event.device_id == DEVICE_ID
        assert event.run_ids == ["11111111-1111-1111-1111-111111111111"]
        assert event.point_count == 1
    finally:
        subscription.close()


def test_uploading_measurements_dedupes_run_ids_across_the_batch(db_session, test_client):
    _register_device(db_session)
    subscription = upload_broadcaster.subscribe(user_id=1)
    second = {**VALID_DATAPOINT, "timestamp": "2026-07-30T12:00:05.000000Z"}
    try:
        response = test_client.post(
            MEASUREMENTS_URL, json=[VALID_DATAPOINT, second], headers=DEVICE_HEADERS
        )

        assert response.status_code == 200
        event = subscription.queue.get_nowait()
        assert event.run_ids == ["11111111-1111-1111-1111-111111111111"]
        assert event.point_count == 2
    finally:
        subscription.close()


def test_rejected_upload_publishes_nothing(db_session, test_client):
    _register_device(db_session)
    subscription = upload_broadcaster.subscribe(user_id=1)
    try:
        response = test_client.post(
            MEASUREMENTS_URL,
            json=[VALID_DATAPOINT],
            headers={"X-Device-ID": DEVICE_ID, "X-Device-Key": "wrong-key"},
        )

        assert response.status_code == 401
        assert subscription.queue.empty()
    finally:
        subscription.close()
