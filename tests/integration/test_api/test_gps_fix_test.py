"""Integration tests for the live GPS-fix-finding diagnostic endpoints.

Full round trip against a real Postgres (tests/integration/conftest.py), mirroring
test_commands.py's setup - registers a real device and logs in as a real superuser. Covers the
device-push/superuser-read auth boundary, the device_id path/auth mismatch check, upsert (no
history) behavior, and the staleness cutoff on GET.
"""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from app.models import Device, GpsFixTestStatus
from app.models.user import User

password_helper = PasswordHelper()

STATUS_URL = "/devices/{device_id}/gps-fix-test/status"

KNOWN_DEVICE_ID = "gps-fix-test-device-01"
KNOWN_DEVICE_KEY = "correct-horse-battery-staple"
DEVICE_HEADERS = {"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": KNOWN_DEVICE_KEY}

VALID_STATUS_PAYLOAD = {"num_satellites": 7, "has_fix": True, "elapsed_s": 42}


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


def _create_superuser(db_session: Session, username: str = "admin-user") -> None:
    db_session.add(
        User(
            email=username,
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=True,
            is_verified=False,
        )
    )
    db_session.commit()


def _login(test_client, username: str = "admin-user") -> str:
    response = test_client.post(
        "/auth/login",
        data={"username": username, "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _superuser_headers(db_session: Session, test_client) -> dict:
    _create_superuser(db_session)
    return {"Authorization": f"Bearer {_login(test_client)}"}


# --- Auth boundary --------------------------------------------------------


def test_post_status_accepts_device_key_auth(test_client, db_session):
    _register_device(db_session)

    response = test_client.post(
        STATUS_URL.format(device_id=KNOWN_DEVICE_ID),
        json=VALID_STATUS_PAYLOAD,
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 200, response.text


def test_post_status_rejects_superuser_jwt_only(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    response = test_client.post(
        STATUS_URL.format(device_id=KNOWN_DEVICE_ID),
        json=VALID_STATUS_PAYLOAD,
        headers=headers,
    )

    assert response.status_code == 401


def test_post_status_device_id_mismatch_returns_403(test_client, db_session):
    _register_device(db_session)
    _register_device(db_session, "some-other-device")

    response = test_client.post(
        STATUS_URL.format(device_id="some-other-device"),
        json=VALID_STATUS_PAYLOAD,
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 403


def test_get_status_rejects_device_key_auth(test_client, db_session):
    _register_device(db_session)

    response = test_client.get(
        STATUS_URL.format(device_id=KNOWN_DEVICE_ID), headers=DEVICE_HEADERS
    )

    assert response.status_code == 401


def test_get_status_rejects_non_superuser(test_client, db_session):
    _register_device(db_session)
    db_session.add(
        User(
            email="regular-user",
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
    )
    db_session.commit()
    token = _login(test_client, "regular-user")

    response = test_client.get(
        STATUS_URL.format(device_id=KNOWN_DEVICE_ID),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_get_status_for_unknown_device_returns_404(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.get(
        STATUS_URL.format(device_id="no-such-device"), headers=headers
    )

    assert response.status_code == 404


# --- Payload validation -----------------------------------------------------


def test_post_status_rejects_out_of_bounds_num_satellites(test_client, db_session):
    _register_device(db_session)

    response = test_client.post(
        STATUS_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"num_satellites": -1, "has_fix": True, "elapsed_s": 10},
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 422


# --- Read-your-write / no history -------------------------------------------


def test_pushed_status_is_visible_on_get(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    test_client.post(
        STATUS_URL.format(device_id=KNOWN_DEVICE_ID),
        json=VALID_STATUS_PAYLOAD,
        headers=DEVICE_HEADERS,
    )

    response = test_client.get(STATUS_URL.format(device_id=KNOWN_DEVICE_ID), headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["run_active"] is True
    assert body["num_satellites"] == 7
    assert body["has_fix"] is True
    assert body["elapsed_s"] == 42


def test_get_status_with_no_report_ever_received_is_not_active(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    response = test_client.get(STATUS_URL.format(device_id=KNOWN_DEVICE_ID), headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "run_active": False,
        "num_satellites": None,
        "has_fix": None,
        "elapsed_s": None,
        "updated_at": None,
    }


def test_second_push_overwrites_the_first_rather_than_keeping_history(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    test_client.post(
        STATUS_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"num_satellites": 3, "has_fix": False, "elapsed_s": 5},
        headers=DEVICE_HEADERS,
    )
    test_client.post(
        STATUS_URL.format(device_id=KNOWN_DEVICE_ID),
        json=VALID_STATUS_PAYLOAD,
        headers=DEVICE_HEADERS,
    )

    response = test_client.get(STATUS_URL.format(device_id=KNOWN_DEVICE_ID), headers=headers)

    assert response.json()["num_satellites"] == 7
    assert (
        db_session.query(GpsFixTestStatus)
        .filter_by(device_id=KNOWN_DEVICE_ID)
        .count()
        == 1
    )


def test_stale_report_reads_as_no_run_active(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    test_client.post(
        STATUS_URL.format(device_id=KNOWN_DEVICE_ID),
        json=VALID_STATUS_PAYLOAD,
        headers=DEVICE_HEADERS,
    )
    row = db_session.get(GpsFixTestStatus, KNOWN_DEVICE_ID)
    row.updated_at = datetime.now(UTC) - timedelta(minutes=5)
    db_session.commit()

    response = test_client.get(STATUS_URL.format(device_id=KNOWN_DEVICE_ID), headers=headers)

    assert response.json()["run_active"] is False
