"""Integration tests for GET /api/devices, the device-listing endpoint powering
the Remote Configuration page's device-selection dropdown. See test_commands.py for the
sibling superuser-JWT-gated queuing API this list feeds into.
"""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from app.models import Device, Heartbeat
from app.models.user import User

password_helper = PasswordHelper()

DEVICES_URL = "/devices"

KNOWN_DEVICE_ID = "devices-test-device-01"
KNOWN_DEVICE_KEY = "correct-horse-battery-staple"
DEVICE_HEADERS = {"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": KNOWN_DEVICE_KEY}


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


def _add_heartbeat(db_session: Session, device_id: str, received_at: datetime) -> None:
    db_session.add(
        Heartbeat(
            device_id=device_id,
            received_at=received_at,
            datapoints_total=1,
            datapoints_valid=1,
            datapoints_invalid=0,
            pipeline_broken=False,
            storage_pending_files=0,
            storage_disk_free_bytes=0,
        )
    )
    db_session.commit()


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


def _login(test_client: TestClient, username: str = "admin-user") -> str:
    response = test_client.post(
        "/auth/login",
        data={"username": username, "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _superuser_headers(db_session: Session, test_client: TestClient) -> dict:
    _create_superuser(db_session)
    return {"Authorization": f"Bearer {_login(test_client)}"}


def test_list_devices_requires_auth(test_client, db_session):
    _register_device(db_session)

    response = test_client.get(DEVICES_URL)

    assert response.status_code == 401


def test_list_devices_rejects_device_key_auth(test_client, db_session):
    _register_device(db_session)

    response = test_client.get(DEVICES_URL, headers=DEVICE_HEADERS)

    assert response.status_code in (401, 403)


def test_list_devices_allows_non_superuser_active_user(test_client, db_session):
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

    response = test_client.get(DEVICES_URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["devices"][0]["device_id"] == KNOWN_DEVICE_ID


def test_list_devices_includes_device_with_no_heartbeats_yet(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    response = test_client.get(DEVICES_URL, headers=headers)

    assert response.status_code == 200
    devices = response.json()["devices"]
    assert len(devices) == 1
    assert devices[0]["device_id"] == KNOWN_DEVICE_ID
    assert devices[0]["online"] is False
    assert devices[0]["last_heartbeat_at"] is None


def test_list_devices_reports_recent_heartbeat_as_online(test_client, db_session):
    _register_device(db_session)
    _add_heartbeat(db_session, KNOWN_DEVICE_ID, datetime.now(UTC))
    headers = _superuser_headers(db_session, test_client)

    response = test_client.get(DEVICES_URL, headers=headers)

    device = response.json()["devices"][0]
    assert device["online"] is True
    assert device["last_heartbeat_at"] is not None


def test_list_devices_reports_stale_heartbeat_as_offline(test_client, db_session):
    _register_device(db_session)
    _add_heartbeat(db_session, KNOWN_DEVICE_ID, datetime.now(UTC) - timedelta(hours=1))
    headers = _superuser_headers(db_session, test_client)

    response = test_client.get(DEVICES_URL, headers=headers)

    device = response.json()["devices"][0]
    assert device["online"] is False


def test_list_devices_uses_most_recent_of_multiple_heartbeats(test_client, db_session):
    _register_device(db_session)
    _add_heartbeat(db_session, KNOWN_DEVICE_ID, datetime.now(UTC) - timedelta(hours=1))
    _add_heartbeat(db_session, KNOWN_DEVICE_ID, datetime.now(UTC))
    headers = _superuser_headers(db_session, test_client)

    response = test_client.get(DEVICES_URL, headers=headers)

    device = response.json()["devices"][0]
    assert device["online"] is True
