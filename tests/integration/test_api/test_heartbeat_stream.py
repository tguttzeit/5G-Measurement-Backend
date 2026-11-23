"""Integration tests for GET /heartbeat/stream and the publish in POST /heartbeat.

A live SSE response never ends, so these subscribe to the broadcaster directly to observe what
the real `POST /heartbeat` publishes, and use the HTTP layer only for the responses that
terminate (auth, 404, 429). The streamed framing itself is covered in
tests/unit/test_heartbeat_stream.py.
"""
import hashlib
import secrets

import pytest
from fastapi_users.password import PasswordHelper

from app.heartbeat_events import heartbeat_broadcaster
from app.models import Device
from app.models.user import User

password_helper = PasswordHelper()

STREAM_URL = "/heartbeat/stream"

DEVICE_ID = "stream-test-device-01"
OTHER_DEVICE_ID = "stream-test-device-02"
DEVICE_KEY = "correct-horse-battery-staple"

VALID_HEARTBEAT_BODY = {
    "since_run_start": {"datapoints_total": 100, "good": 80, "bad": 15, "invalid": 5},
    "pipeline_broken": False,
    "storage": {"pending_files": 3, "disk_free_bytes": 50000000000},
}


def _register_device(db_session, device_id: str) -> None:
    db_session.add(
        Device(
            device_id=device_id,
            api_key_hash=hashlib.sha256(DEVICE_KEY.encode()).hexdigest(),
            hmac_secret=secrets.token_hex(32),
        )
    )
    db_session.commit()


def _user_headers(db_session, test_client, email: str = "regular-user") -> dict:
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


def _post_heartbeat(test_client, device_id: str):
    return test_client.post(
        "/heartbeat",
        json=VALID_HEARTBEAT_BODY,
        headers={"X-Device-ID": device_id, "X-Device-Key": DEVICE_KEY},
    )


@pytest.fixture(autouse=True)
def _no_leftover_subscribers():
    yield
    assert heartbeat_broadcaster.total_subscribers == 0


def test_stream_requires_auth(test_client, db_session):
    _register_device(db_session, DEVICE_ID)

    response = test_client.get(STREAM_URL, params={"device_id": DEVICE_ID})

    assert response.status_code == 401


def test_stream_rejects_device_key_auth(test_client, db_session):
    _register_device(db_session, DEVICE_ID)

    response = test_client.get(
        STREAM_URL,
        params={"device_id": DEVICE_ID},
        headers={"X-Device-ID": DEVICE_ID, "X-Device-Key": DEVICE_KEY},
    )

    assert response.status_code in (401, 403)


def test_stream_unknown_device_is_404(test_client, db_session):
    headers = _user_headers(db_session, test_client)

    response = test_client.get(STREAM_URL, params={"device_id": "no-such-device"}, headers=headers)

    assert response.status_code == 404


def test_stream_over_the_per_user_cap_is_429(test_client, db_session):
    _register_device(db_session, DEVICE_ID)
    headers = _user_headers(db_session, test_client)
    user_id = db_session.query(User).one().id
    held = [heartbeat_broadcaster.subscribe(DEVICE_ID, user_id) for _ in range(5)]
    try:
        response = test_client.get(STREAM_URL, params={"device_id": DEVICE_ID}, headers=headers)
    finally:
        for subscription in held:
            subscription.close()

    assert response.status_code == 429


def test_stream_is_not_shadowed_by_the_device_id_route(test_client, db_session):
    headers = _user_headers(db_session, test_client)

    response = test_client.get(STREAM_URL, params={"device_id": "no-such-device"}, headers=headers)

    assert "No heartbeats found" not in response.text


def test_posting_a_heartbeat_publishes_a_signal_for_that_device(test_client, db_session):
    _register_device(db_session, DEVICE_ID)
    subscription = heartbeat_broadcaster.subscribe(DEVICE_ID, user_id=1)
    try:
        response = _post_heartbeat(test_client, DEVICE_ID)

        assert response.status_code == 200
        event = subscription.queue.get_nowait()
        assert event.device_id == DEVICE_ID
        assert event.received_at is not None
    finally:
        subscription.close()


def test_posting_a_heartbeat_does_not_signal_other_devices(test_client, db_session):
    _register_device(db_session, DEVICE_ID)
    _register_device(db_session, OTHER_DEVICE_ID)
    other = heartbeat_broadcaster.subscribe(OTHER_DEVICE_ID, user_id=1)
    try:
        _post_heartbeat(test_client, DEVICE_ID)

        assert other.queue.empty()
    finally:
        other.close()


def test_rejected_heartbeat_publishes_nothing(test_client, db_session):
    _register_device(db_session, DEVICE_ID)
    subscription = heartbeat_broadcaster.subscribe(DEVICE_ID, user_id=1)
    try:
        response = test_client.post(
            "/heartbeat",
            json=VALID_HEARTBEAT_BODY,
            headers={"X-Device-ID": DEVICE_ID, "X-Device-Key": "wrong-key"},
        )

        assert response.status_code == 401
        assert subscription.queue.empty()
    finally:
        subscription.close()
