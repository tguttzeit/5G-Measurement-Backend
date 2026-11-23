"""Integration tests remote config override / one-shot command API.

Full round trip against a real Postgres (tests/integration/conftest.py) - registers a
real device (mirroring scripts/register_device.py) and logs in as a real superuser (mirroring
test_admin_users.py). Covers what a unit suite could only assert vacuously without a registered
device: the allow-list enforced both directions, config-override persistence, one-shot
at-least-once redelivery deduped by id, HMAC signing of heartbeat responses, and the auth
boundary between the superuser-JWT-gated queuing API and device-key auth.
"""
import hashlib
import hmac as hmac_module
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from app.models import Device
from app.models.commands import CommandType, DeviceCommand
from app.models.user import User
from app.response_signing import sign_heartbeat_response

password_helper = PasswordHelper()

CONFIG_OVERRIDE_URL = "/devices/{device_id}/config-overrides"
COMMAND_URL = "/devices/{device_id}/commands"
QUEUE_URL = "/devices/{device_id}/queue"
HEARTBEAT_URL = "/heartbeat"

KNOWN_DEVICE_ID = "commands-test-device-01"
KNOWN_DEVICE_KEY = "correct-horse-battery-staple"
DEVICE_HEADERS = {"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": KNOWN_DEVICE_KEY}

VALID_HEARTBEAT_BODY = {
    "since_run_start": {"datapoints_total": 100, "good": 80, "bad": 15, "invalid": 5},
    "pipeline_broken": False,
    "storage": {"pending_files": 3, "disk_free_bytes": 50000000000},
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


# --- Auth boundary --------------------------------------------------------


def test_queue_config_override_requires_auth(test_client, db_session):
    _register_device(db_session)

    response = test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"movement_gate_movement_threshold": 100.0},
    )

    assert response.status_code == 401


def test_queue_config_override_rejects_device_key_auth(test_client, db_session):
    _register_device(db_session)

    response = test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"movement_gate_movement_threshold": 100.0},
        headers=DEVICE_HEADERS,
    )

    assert response.status_code in (401, 403)


def test_queue_config_override_rejects_non_superuser(test_client, db_session):
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

    response = test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"movement_gate_movement_threshold": 100.0},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_queue_command_rejects_device_key_auth(test_client, db_session):
    _register_device(db_session)

    response = test_client.post(
        COMMAND_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"command": "force-upload-now"},
        headers=DEVICE_HEADERS,
    )

    assert response.status_code in (401, 403)


def test_get_queue_rejects_device_key_auth(test_client, db_session):
    _register_device(db_session)

    response = test_client.get(QUEUE_URL.format(device_id=KNOWN_DEVICE_ID), headers=DEVICE_HEADERS)

    assert response.status_code in (401, 403)


# --- Allow-list -------------------------------------------------------


def test_test_interval_s_no_longer_allowed(test_client, db_session):
    """`test_interval_s` was dropped from the allow-list - it never mapped to a
    real device concept and is replaced by per-feature cadence fields.
    """
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    response = test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"test_interval_s": 300},
        headers=headers,
    )

    assert response.status_code == 422


def test_new_per_feature_cadence_field_queues_and_appears_in_next_heartbeat(
    test_client, db_session
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    queue_response = test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"latency_test_baseline_interval_s": 900.0},
        headers=headers,
    )
    assert queue_response.status_code == 200, queue_response.text

    heartbeat_response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )

    assert (
        heartbeat_response.json()["config_overrides"]["latency_test_baseline_interval_s"]
        == 900.0
    )


def test_disallowed_override_field_rejected_at_write_time(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    response = test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"upload_host": "evil.example.com"},
        headers=headers,
    )

    assert response.status_code == 422


def test_disallowed_field_never_emitted_even_if_persisted_directly(test_client, db_session):
    """Defense in depth: bypass the write-time allow-list entirely by inserting the row directly
    against the database, the way the schema (not the API) technically allows. The heartbeat
    serializer must still never emit it - see app/routers/heartbeat.py's _ALLOWED_OVERRIDE_FIELDS
    filter.
    """
    from app.models import CommandType, DeviceCommand

    _register_device(db_session)
    db_session.add(
        DeviceCommand(
            device_id=KNOWN_DEVICE_ID,
            type=CommandType.CONFIG_OVERRIDE,
            field="upload_host",
            payload={"value": "evil.example.com"},
        )
    )
    db_session.commit()

    response = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert response.status_code == 200
    assert "upload_host" not in response.json()
    assert "upload_host" not in response.json().get("config_overrides", {})


# --- Config overrides ---------------------------------------------------


def test_permitted_override_field_queues_and_appears_in_next_heartbeat(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    queue_response = test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"movement_gate_movement_threshold": 100.0},
        headers=headers,
    )
    assert queue_response.status_code == 200, queue_response.text

    heartbeat_response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )

    overrides = heartbeat_response.json()["config_overrides"]
    assert overrides["movement_gate_movement_threshold"] == 100.0


def test_config_override_persists_across_multiple_heartbeats_until_changed(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"movement_gate_movement_threshold": 100.0},
        headers=headers,
    )

    first = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)
    second = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert first.json()["config_overrides"]["movement_gate_movement_threshold"] == 100.0
    assert second.json()["config_overrides"]["movement_gate_movement_threshold"] == 100.0


def test_requeuing_same_field_replaces_value_rather_than_duplicating(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"movement_gate_movement_threshold": 100.0},
        headers=headers,
    )
    test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"movement_gate_movement_threshold": 95.0},
        headers=headers,
    )

    heartbeat_response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )

    assert heartbeat_response.json()["config_overrides"]["movement_gate_movement_threshold"] == 95.0

    queue = test_client.get(QUEUE_URL.format(device_id=KNOWN_DEVICE_ID), headers=headers).json()
    rsrp_entries = [e for e in queue["queue"] if e["field"] == "movement_gate_movement_threshold"]
    assert len(rsrp_entries) == 1


# --- One-shot commands ---------------------------------------------------


def test_permitted_command_can_be_queued_and_appears_in_next_heartbeat(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    queue_response = test_client.post(
        COMMAND_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"command": "force-upload-now"},
        headers=headers,
    )
    assert queue_response.status_code == 200, queue_response.text
    command_id = queue_response.json()["command_id"]

    heartbeat_response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )

    queued_commands = heartbeat_response.json()["commands"]
    assert any(
        c["command"] == "force-upload-now" and c["id"] == command_id for c in queued_commands
    )


@pytest.mark.parametrize(
    "command",
    [
        "mode-manual-now",
        "mode-auto-now",
        "start-measuring-now",
        "run-selftest-now",
        "run-gps-fix-test-now",
        "stop-gps-fix-test-now",
    ],
)
def test_mode_switch_and_manual_mode_commands_can_be_queued_and_appear_in_next_heartbeat(
    test_client, db_session, command
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    queue_response = test_client.post(
        COMMAND_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"command": command},
        headers=headers,
    )
    assert queue_response.status_code == 200, queue_response.text
    command_id = queue_response.json()["command_id"]

    heartbeat_response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )

    queued_commands = heartbeat_response.json()["commands"]
    assert any(c["command"] == command and c["id"] == command_id for c in queued_commands)


def test_force_upload_with_speed_rejected_with_422(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    response = test_client.post(
        COMMAND_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"command": "force-upload-now", "speed": 50},
        headers=headers,
    )

    assert response.status_code == 422


def test_invalid_command_rejected_with_422(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    response = test_client.post(
        COMMAND_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"command": "rm-rf-now"},
        headers=headers,
    )

    assert response.status_code == 422


def test_one_shot_command_redelivery_is_deduped_by_command_id(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    queue_response = test_client.post(
        COMMAND_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"command": "force-upload-now"},
        headers=headers,
    )
    command_id = queue_response.json()["command_id"]

    first = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)
    second = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    first_ids = {c["id"] for c in first.json()["commands"]}
    second_ids = {c["id"] for c in second.json()["commands"]}
    assert command_id in first_ids
    assert command_id in second_ids


def test_deleting_queued_command_stops_redelivery(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    queue_response = test_client.post(
        COMMAND_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"command": "shutdown-now"},
        headers=headers,
    )
    command_id = queue_response.json()["command_id"]

    delete_response = test_client.delete(
        f"{QUEUE_URL.format(device_id=KNOWN_DEVICE_ID)}/{command_id}", headers=headers
    )
    assert delete_response.status_code == 200

    heartbeat_response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )

    assert "commands" not in heartbeat_response.json()


# --- Heartbeat response signing ------------------------------------------


def test_heartbeat_response_is_hmac_signed(test_client, db_session):
    _register_device(db_session)

    response = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert "signature" in response.json()
    assert response.json()["signature"].startswith("hmac-sha256:")


def test_heartbeat_response_signature_is_verifiable_with_device_secret(test_client, db_session):
    device = _register_device(db_session)

    response = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    body = dict(response.json())
    signature = body.pop("signature")
    expected = sign_heartbeat_response(device, body)
    assert hmac_module.compare_digest(signature, expected)


def test_heartbeat_response_signature_changes_when_payload_changes(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"movement_gate_movement_threshold": 100.0},
        headers=headers,
    )
    before = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"movement_gate_movement_threshold": 95.0},
        headers=headers,
    )
    after = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert before.json()["signature"] != after.json()["signature"]


def test_heartbeat_with_nothing_pending_is_unchanged_from_current_shape(test_client, db_session):
    _register_device(db_session)

    response = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "config_overrides" not in response.json()
    assert "commands" not in response.json()


# --- Unknown device --------------------------------------------------------


def test_queue_config_override_for_unknown_device_returns_404(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id="no-such-device"),
        json={"movement_gate_movement_threshold": 100.0},
        headers=headers,
    )

    assert response.status_code == 404


# --- Clear queue (bulk delete) --------------------------------------------


def test_clear_queue_removes_config_overrides_and_commands(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"movement_gate_movement_threshold": 100.0},
        headers=headers,
    )
    test_client.post(
        COMMAND_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"command": "force-upload-now"},
        headers=headers,
    )

    response = test_client.delete(QUEUE_URL.format(device_id=KNOWN_DEVICE_ID), headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"

    queue = test_client.get(QUEUE_URL.format(device_id=KNOWN_DEVICE_ID), headers=headers).json()
    assert queue["queue"] == []

    heartbeat_response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )
    assert "config_overrides" not in heartbeat_response.json()
    assert "commands" not in heartbeat_response.json()


def test_clear_queue_on_empty_queue_returns_200_with_zero_deleted(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    response = test_client.delete(QUEUE_URL.format(device_id=KNOWN_DEVICE_ID), headers=headers)

    assert response.status_code == 200
    assert "0" in response.json()["message"]


def test_clear_queue_does_not_affect_other_devices(test_client, db_session):
    _register_device(db_session)
    other_device_id = "commands-test-device-02"
    _register_device(db_session, device_id=other_device_id)
    headers = _superuser_headers(db_session, test_client)

    test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={"movement_gate_movement_threshold": 100.0},
        headers=headers,
    )
    test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=other_device_id),
        json={"movement_gate_movement_threshold": 95.0},
        headers=headers,
    )

    test_client.delete(QUEUE_URL.format(device_id=KNOWN_DEVICE_ID), headers=headers)

    other_queue = test_client.get(
        QUEUE_URL.format(device_id=other_device_id), headers=headers
    ).json()
    assert len(other_queue["queue"]) == 1


def test_clear_queue_for_unknown_device_returns_404(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.delete(
        QUEUE_URL.format(device_id="no-such-device"), headers=headers
    )

    assert response.status_code == 404


def test_clear_queue_rejects_non_superuser(test_client, db_session):
    _register_device(db_session)
    db_session.add(
        User(
            email="regular-user-2",
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
    )
    db_session.commit()
    token = _login(test_client, "regular-user-2")

    response = test_client.delete(
        QUEUE_URL.format(device_id=KNOWN_DEVICE_ID),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_clear_queue_rejects_device_key_auth(test_client, db_session):
    _register_device(db_session)

    response = test_client.delete(
        QUEUE_URL.format(device_id=KNOWN_DEVICE_ID), headers=DEVICE_HEADERS
    )

    assert response.status_code in (401, 403)


# --- stop-measuring-now / reboot-now / promote-overrides-now ---


def _queue_command(test_client, headers, command, device_id=KNOWN_DEVICE_ID):
    response = test_client.post(
        COMMAND_URL.format(device_id=device_id), json={"command": command}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["command_id"]


def _queue_override(test_client, headers, value, device_id=KNOWN_DEVICE_ID):
    response = test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=device_id),
        json={"movement_gate_movement_threshold": value},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _queue_types(test_client, headers, device_id=KNOWN_DEVICE_ID):
    queue = test_client.get(QUEUE_URL.format(device_id=device_id), headers=headers).json()["queue"]
    return [entry["type"] for entry in queue]


@pytest.mark.parametrize("command", ["stop-measuring-now", "reboot-now", "promote-overrides-now"])
def test_new_commands_can_be_queued_and_appear_in_next_heartbeat(
    test_client, db_session, command
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, command)

    heartbeat_response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )

    assert {"id": command_id, "command": command} in heartbeat_response.json()["commands"]


def test_promote_overrides_delivery_includes_overrides_then_deletes_them(
    test_client, db_session
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    _queue_override(test_client, headers, 100.0)
    _queue_command(test_client, headers, "promote-overrides-now")

    heartbeat_response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )

    assert heartbeat_response.json()["config_overrides"] == {
        "movement_gate_movement_threshold": 100.0
    }
    assert "config_override" not in _queue_types(test_client, headers)
    next_heartbeat = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )
    assert "config_overrides" not in next_heartbeat.json()


def test_promote_overrides_queued_does_not_delete_overrides_before_delivery(
    test_client, db_session
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    _queue_override(test_client, headers, 100.0)
    _queue_command(test_client, headers, "promote-overrides-now")

    assert "config_override" in _queue_types(test_client, headers)


def test_promote_overrides_redelivery_keeps_overrides_queued_after_first_delivery(
    test_client, db_session
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    _queue_command(test_client, headers, "promote-overrides-now")
    test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    _queue_override(test_client, headers, 90.0)
    redelivery = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )

    assert redelivery.json()["config_overrides"] == {"movement_gate_movement_threshold": 90.0}
    assert "config_override" in _queue_types(test_client, headers)


def test_promote_overrides_cleanup_is_scoped_to_authenticated_device(test_client, db_session):
    _register_device(db_session)
    other_device_id = "commands-test-device-02"
    _register_device(db_session, device_id=other_device_id)
    headers = _superuser_headers(db_session, test_client)
    _queue_override(test_client, headers, 100.0)
    _queue_override(test_client, headers, 95.0, device_id=other_device_id)
    _queue_command(test_client, headers, "promote-overrides-now")

    test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert _queue_types(test_client, headers, device_id=other_device_id) == ["config_override"]


def test_commands_with_identical_created_at_are_delivered_in_id_order(test_client, db_session):
    _register_device(db_session)
    same_timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        DeviceCommand(
            device_id=KNOWN_DEVICE_ID,
            type=CommandType.ONE_SHOT,
            payload={"command": command},
            created_at=same_timestamp,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        for command in ("mode-auto-now", "reboot-now", "force-upload-now")
    ]
    db_session.add_all(rows)
    db_session.commit()

    heartbeat_response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS
    )

    delivered = [c["command"] for c in heartbeat_response.json()["commands"]]
    assert delivered == ["mode-auto-now", "reboot-now", "force-upload-now"]
