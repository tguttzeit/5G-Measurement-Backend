"""Integration tests for the typed remote config overrides, valid/invalid counts and heartbeat
nonce.
"""
import hashlib
import hmac as hmac_module
import json
import secrets

import pytest
from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device, Heartbeat
from app.models.user import User
from app.response_signing import sign_heartbeat_response
from app.routers.heartbeat import _MAX_CURRENT_CONFIG_BYTES
from app.schemas.commands import ConfigOverrideCreate

DEVICE_ID = "typed-overrides-device"
DEVICE_KEY = "correct-horse-battery-staple"
DEVICE_HEADERS = {"X-Device-ID": DEVICE_ID, "X-Device-Key": DEVICE_KEY}
OVERRIDE_URL = f"/devices/{DEVICE_ID}/config-overrides"
NONCE = "9f3c1a7e5b2d4c88a1e06f3b7d92c4aa"

NEW_HEARTBEAT = {
    "since_run_start": {"datapoints_total": 142, "valid": 138, "invalid": 4},
    "pipeline_broken": False,
    "storage": {"pending_files": 3, "disk_free_bytes": 48000000000},
}

password_helper = PasswordHelper()


def _register_device(db_session: Session) -> Device:
    device = Device(
        device_id=DEVICE_ID,
        api_key_hash=hashlib.sha256(DEVICE_KEY.encode()).hexdigest(),
        hmac_secret=secrets.token_hex(32),
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return device


def _superuser_headers(db_session: Session, test_client: TestClient) -> dict:
    db_session.add(
        User(
            email="admin-user",
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=True,
            is_verified=False,
        )
    )
    db_session.commit()
    response = test_client.post(
        "/auth/login", data={"username": "admin-user", "password": "correct-horse-battery-staple"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _heartbeat(test_client: TestClient, **extra) -> dict:
    response = test_client.post(
        "/heartbeat", json={**NEW_HEARTBEAT, **extra}, headers=DEVICE_HEADERS
    )
    assert response.status_code == 200, response.text
    return response.json()


def _queue(test_client, headers, overrides):
    return test_client.post(OVERRIDE_URL, json=overrides, headers=headers)


# --- valid / invalid ------------------------------------------------------------------------


def test_new_device_valid_count_is_stored_and_exposed(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    _heartbeat(test_client)

    stored = db_session.scalars(select(Heartbeat)).one()
    assert (stored.datapoints_valid, stored.datapoints_invalid) == (138, 4)
    for url in ("/heartbeat", f"/heartbeat/{DEVICE_ID}"):
        body = test_client.get(url, headers=headers).json()
        summary = body["heartbeats"][0] if "heartbeats" in body else body
        assert (summary["datapoints_valid"], summary["datapoints_invalid"]) == (138, 4)
        assert "datapoints_good" not in summary and "datapoints_bad" not in summary


def test_old_device_good_and_bad_are_stored_as_valid(test_client, db_session):
    _register_device(db_session)
    old_counts = {"datapoints_total": 100, "good": 80, "bad": 15, "invalid": 5}
    old = {**NEW_HEARTBEAT, "since_run_start": old_counts}

    response = test_client.post("/heartbeat", json=old, headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    stored = db_session.scalars(select(Heartbeat)).one()
    assert (stored.datapoints_valid, stored.datapoints_invalid) == (95, 5)


# --- nonce ----------------------------------------------------------------------------------


def test_nonce_is_echoed_inside_the_signed_body(test_client, db_session):
    device = _register_device(db_session)

    body = _heartbeat(test_client, nonce=NONCE)

    assert body["nonce"] == NONCE
    signature = body.pop("signature")
    assert hmac_module.compare_digest(signature, sign_heartbeat_response(device, body))


def test_signature_covers_the_nonce(test_client, db_session):
    device = _register_device(db_session)

    body = _heartbeat(test_client, nonce=NONCE)

    signature = body.pop("signature")
    body["nonce"] = "0" * 32
    assert not hmac_module.compare_digest(signature, sign_heartbeat_response(device, body))


def test_nonce_is_echoed_on_responses_with_overrides_and_commands(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    _queue(test_client, headers, {"collector_gps_enabled": False})
    test_client.post(
        f"/devices/{DEVICE_ID}/commands", json={"command": "reboot-now"}, headers=headers
    )

    body = _heartbeat(test_client, nonce=NONCE)

    assert body["nonce"] == NONCE
    assert body["config_overrides"] == {"collector_gps_enabled": False}
    assert [c["command"] for c in body["commands"]] == ["reboot-now"]


def test_each_request_gets_its_own_nonce_back(test_client, db_session):
    _register_device(db_session)

    first = _heartbeat(test_client, nonce="a" * 32)
    second = _heartbeat(test_client, nonce="b" * 32)

    assert (first["nonce"], second["nonce"]) == ("a" * 32, "b" * 32)


def test_no_nonce_in_the_response_when_the_request_had_none(test_client, db_session):
    device = _register_device(db_session)

    body = _heartbeat(test_client)

    assert "nonce" not in body
    signature = body.pop("signature")
    assert hmac_module.compare_digest(signature, sign_heartbeat_response(device, body))


@pytest.mark.parametrize("nonce", ["a" * 65, "", "ab cd", "ab-cd", 'a"b', "ab\n", 12345])
def test_invalid_nonce_is_rejected_and_nothing_is_stored(test_client, db_session, nonce):
    _register_device(db_session)

    response = test_client.post(
        "/heartbeat", json={**NEW_HEARTBEAT, "nonce": nonce}, headers=DEVICE_HEADERS
    )

    assert response.status_code == 422
    assert db_session.scalars(select(Heartbeat)).all() == []


# --- typed overrides ------------------------------------------------------------------------


def test_typed_overrides_are_delivered_with_their_json_types(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    overrides = {
        "collector_capture_gate": "time",
        "collector_capture_interval_s": 30.5,
        "collector_gps_enabled": False,
        "gnss_receiver_retries": 5,
        "movement_gate_home_latitude": 52.5,
    }
    assert _queue(test_client, headers, overrides).status_code == 200

    delivered = _heartbeat(test_client)["config_overrides"]

    assert delivered == overrides
    assert delivered["collector_gps_enabled"] is False
    assert type(delivered["gnss_receiver_retries"]) is int


def test_null_override_survives_to_the_signed_response(test_client, db_session):
    device = _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    queued = _queue(
        test_client,
        headers,
        {"movement_gate_home_latitude": None, "movement_gate_home_longitude": None},
    )
    assert queued.status_code == 200, queued.text
    assert queued.json()["config_overrides"] == {
        "movement_gate_home_latitude": None,
        "movement_gate_home_longitude": None,
    }

    response = test_client.post("/heartbeat", json=NEW_HEARTBEAT, headers=DEVICE_HEADERS)

    body = response.json()
    assert body["config_overrides"] == {
        "movement_gate_home_latitude": None,
        "movement_gate_home_longitude": None,
    }
    # The signature is computed over exactly what the device receives.
    signature = body.pop("signature")
    assert json.loads(json.dumps(body)) == body
    assert hmac_module.compare_digest(signature, sign_heartbeat_response(device, body))


@pytest.mark.parametrize(
    "overrides",
    [
        {"system_mode": "waiting"},
        {"rsrp_threshold": -100},
        {"system_shutdown_gpio": 17},
        {"gnss_receiver_retries": 21},
        {"gnss_receiver_retries": True},
        {"collector_capture_gate": "Time"},
        {"collector_gps_enabled": 1},
        {"collector_position_threshold": "5"},
        {"collector_capture_interval_s": None},
        {"hmac_secret": "x"},
    ],
)
def test_invalid_overrides_are_rejected_and_not_queued(test_client, db_session, overrides):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    response = _queue(test_client, headers, overrides)

    assert response.status_code == 422
    queue = test_client.get(f"/devices/{DEVICE_ID}/queue", headers=headers).json()["queue"]
    assert queue == []


def test_validation_errors_do_not_echo_the_submitted_value(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    response = _queue(test_client, headers, {"movement_gate_home_latitude": 123456.789})

    assert response.status_code == 422
    assert "123456.789" not in response.text
    assert response.json()["detail"][0]["loc"] == ["body", "movement_gate_home_latitude"]


def test_overrides_require_a_superuser(test_client, db_session):
    _register_device(db_session)

    response = _queue(test_client, {}, {"collector_gps_enabled": True})

    assert response.status_code == 401


# --- applied detection per type -------------------------------------------------------------


def _states(test_client, headers) -> dict[str, str]:
    items = test_client.get(f"/devices/{DEVICE_ID}/command-status", headers=headers).json()["items"]
    return {item["name"]: item["state"] for item in items}


def test_bool_enum_and_null_overrides_reach_success(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    overrides = {
        "collector_gps_enabled": False,
        "collector_capture_gate": "time",
        "movement_gate_home_latitude": None,
    }
    _queue(test_client, headers, overrides)
    _heartbeat(test_client, current_config={"collector_gps_enabled": True})
    assert set(_states(test_client, headers).values()) == {"delivered"}

    _heartbeat(
        test_client,
        current_config={
            "collector_gps_enabled": False,
            "collector_capture_gate": "time",
            "movement_gate_home_latitude": None,
        },
    )

    assert _states(test_client, headers) == {name: "success" for name in overrides}


# --- current_config size --------------------------------------------------------------------


def test_current_config_with_every_override_key_fits_the_size_cap(test_client, db_session):
    _register_device(db_session)
    current_config = {
        field: "serving_cell" if field == "modem_mode" else 1234567.890123
        for field in ConfigOverrideCreate.model_fields
    }
    current_config.update({"system_mode": "waiting", "mode": "waiting"})
    size = len(json.dumps(current_config).encode())
    assert size < _MAX_CURRENT_CONFIG_BYTES / 2, f"{size} bytes is too close to the cap"

    _heartbeat(test_client, current_config=current_config)

    assert db_session.scalars(select(Heartbeat)).one().current_config == current_config
