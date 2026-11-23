"""Integration tests for command-ack handling in POST /heartbeat and GET /commands/stream
: clearing the queue row on a terminal ack, the shutdown-now/
reboot-now "received"-is-terminal special case, and publishing to command_ack_broadcaster.
"""
import hashlib
import secrets

import pytest
from fastapi_users.password import PasswordHelper

from app.command_events import command_ack_broadcaster
from app.models import Device
from app.models.user import User

password_helper = PasswordHelper()

COMMAND_URL = "/devices/{device_id}/commands"
QUEUE_URL = "/devices/{device_id}/queue"
HEARTBEAT_URL = "/heartbeat"
STREAM_URL = "/commands/stream"

DEVICE_ID = "ack-test-device-01"
OTHER_DEVICE_ID = "ack-test-device-02"
DEVICE_KEY = "correct-horse-battery-staple"
DEVICE_HEADERS = {"X-Device-ID": DEVICE_ID, "X-Device-Key": DEVICE_KEY}
OTHER_DEVICE_HEADERS = {"X-Device-ID": OTHER_DEVICE_ID, "X-Device-Key": DEVICE_KEY}

VALID_HEARTBEAT_BODY = {
    "since_run_start": {"datapoints_total": 100, "good": 80, "bad": 15, "invalid": 5},
    "pipeline_broken": False,
    "storage": {"pending_files": 3, "disk_free_bytes": 50000000000},
}


def _register_device(db_session, device_id: str = DEVICE_ID) -> None:
    db_session.add(
        Device(
            device_id=device_id,
            api_key_hash=hashlib.sha256(DEVICE_KEY.encode()).hexdigest(),
            hmac_secret=secrets.token_hex(32),
        )
    )
    db_session.commit()


def _superuser_headers(db_session, test_client, email: str = "ack-test-superuser") -> dict:
    db_session.add(
        User(
            email=email,
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=True,
            is_verified=False,
        )
    )
    db_session.commit()
    response = test_client.post(
        "/auth/login", data={"username": email, "password": "correct-horse-battery-staple"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _regular_user_headers(db_session, test_client, email: str = "ack-test-regular") -> dict:
    db_session.add(
        User(
            email=email,
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
    )
    db_session.commit()
    response = test_client.post(
        "/auth/login", data={"username": email, "password": "correct-horse-battery-staple"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _queue_command(test_client, headers, command: str, device_id: str = DEVICE_ID) -> int:
    response = test_client.post(
        COMMAND_URL.format(device_id=device_id), json={"command": command}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["command_id"]


def _queue_ids(test_client, headers, device_id: str = DEVICE_ID) -> set[int]:
    response = test_client.get(QUEUE_URL.format(device_id=device_id), headers=headers)
    assert response.status_code == 200, response.text
    return {entry["id"] for entry in response.json()["queue"]}


def _heartbeat_with_ack(device_headers, *acks) -> dict:
    return {**VALID_HEARTBEAT_BODY, "executed_commands": list(acks)}


@pytest.fixture(autouse=True)
def _no_leftover_subscribers():
    yield
    assert command_ack_broadcaster.total_subscribers == 0


# --- Queue clearing on terminal ack ----------------------------------------


def test_success_ack_clears_the_queue_row(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "force-upload-now")

    response = test_client.post(
        HEARTBEAT_URL,
        json=_heartbeat_with_ack(
            DEVICE_HEADERS, {"id": command_id, "command": "force-upload-now", "status": "success"}
        ),
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 200, response.text
    assert command_id not in _queue_ids(test_client, headers)


def test_acked_command_is_not_redelivered_in_the_same_response(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "force-upload-now")

    response = test_client.post(
        HEARTBEAT_URL,
        json=_heartbeat_with_ack(
            DEVICE_HEADERS, {"id": command_id, "command": "force-upload-now", "status": "success"}
        ),
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 200, response.text
    redelivered_ids = {c["id"] for c in response.json().get("commands", [])}
    assert command_id not in redelivered_ids


def test_failed_ack_clears_the_queue_row_too(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "sim-reset-now")

    response = test_client.post(
        HEARTBEAT_URL,
        json=_heartbeat_with_ack(
            DEVICE_HEADERS,
            {
                "id": command_id,
                "command": "sim-reset-now",
                "status": "failed",
                "error": "SIM not detected",
            },
        ),
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 200, response.text
    assert command_id not in _queue_ids(test_client, headers)


def test_not_applicable_ack_clears_the_queue_row(test_client, db_session):
    # Added device-side without being announced here first - this is the exact value that
    # 422ed every subsequent heartbeat from 5gmu_1 before `status` was loosened to a plain str.
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "sim-reset-now")

    response = test_client.post(
        HEARTBEAT_URL,
        json=_heartbeat_with_ack(
            DEVICE_HEADERS,
            {
                "id": command_id,
                "command": "sim-reset-now",
                "status": "not_applicable",
                "error": "No active measurement",
            },
        ),
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 200, response.text
    assert command_id not in _queue_ids(test_client, headers)


def test_unrecognized_ack_status_does_not_422_and_leaves_command_queued(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "force-upload-now")

    response = test_client.post(
        HEARTBEAT_URL,
        json=_heartbeat_with_ack(
            DEVICE_HEADERS,
            {"id": command_id, "command": "force-upload-now", "status": "some-future-status"},
        ),
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 200, response.text
    assert command_id in _queue_ids(test_client, headers)


def test_received_ack_clears_the_queue_for_shutdown_now(test_client, db_session):
    # shutdown-now has no later point at which the device could report anything more -
    # "received" is as final as it gets.
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "shutdown-now")

    response = test_client.post(
        HEARTBEAT_URL,
        json=_heartbeat_with_ack(
            DEVICE_HEADERS, {"id": command_id, "command": "shutdown-now", "status": "received"}
        ),
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 200, response.text
    assert command_id not in _queue_ids(test_client, headers)


def test_received_ack_does_not_clear_reboot_now_but_a_later_success_does(test_client, db_session):
    # Unlike shutdown-now, reboot-now acks twice across two heartbeats: "received" when the
    # device gets the command, "success" once it's back up. The row must survive the first ack
    # so the second one has something to clear.
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "reboot-now")

    received_response = test_client.post(
        HEARTBEAT_URL,
        json=_heartbeat_with_ack(
            DEVICE_HEADERS, {"id": command_id, "command": "reboot-now", "status": "received"}
        ),
        headers=DEVICE_HEADERS,
    )

    assert received_response.status_code == 200, received_response.text
    assert command_id in _queue_ids(test_client, headers)

    success_response = test_client.post(
        HEARTBEAT_URL,
        json=_heartbeat_with_ack(
            DEVICE_HEADERS, {"id": command_id, "command": "reboot-now", "status": "success"}
        ),
        headers=DEVICE_HEADERS,
    )

    assert success_response.status_code == 200, success_response.text
    assert command_id not in _queue_ids(test_client, headers)


def test_received_ack_does_not_clear_a_non_shutdown_reboot_command(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "force-upload-now")

    response = test_client.post(
        HEARTBEAT_URL,
        json=_heartbeat_with_ack(
            DEVICE_HEADERS, {"id": command_id, "command": "force-upload-now", "status": "received"}
        ),
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 200, response.text
    assert command_id in _queue_ids(test_client, headers)


def test_ack_for_unknown_id_is_ignored(test_client, db_session):
    _register_device(db_session)

    response = test_client.post(
        HEARTBEAT_URL,
        json=_heartbeat_with_ack(
            DEVICE_HEADERS, {"id": 999999, "command": "force-upload-now", "status": "success"}
        ),
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 200, response.text


def test_ack_cannot_clear_another_devices_command(test_client, db_session):
    _register_device(db_session, DEVICE_ID)
    _register_device(db_session, OTHER_DEVICE_ID)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "force-upload-now", device_id=DEVICE_ID)

    response = test_client.post(
        HEARTBEAT_URL,
        json=_heartbeat_with_ack(
            OTHER_DEVICE_HEADERS,
            {"id": command_id, "command": "force-upload-now", "status": "success"},
        ),
        headers=OTHER_DEVICE_HEADERS,
    )

    assert response.status_code == 200, response.text
    assert command_id in _queue_ids(test_client, headers, device_id=DEVICE_ID)


def test_heartbeat_without_executed_commands_still_works(test_client, db_session):
    _register_device(db_session)

    response = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text


# --- Publishing to the command-ack stream ----------------------------------


def test_reboot_nows_non_terminal_received_still_publishes_to_broadcaster(test_client, db_session):
    # Non-terminal, but the dashboard still needs to show "device is rebooting" - only the
    # queue-clearing is deferred to the later "success", not the notification.
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "reboot-now")
    subscription = command_ack_broadcaster.subscribe(user_id=1)
    try:
        test_client.post(
            HEARTBEAT_URL,
            json=_heartbeat_with_ack(
                DEVICE_HEADERS, {"id": command_id, "command": "reboot-now", "status": "received"}
            ),
            headers=DEVICE_HEADERS,
        )

        event = subscription.queue.get_nowait()
        assert event.device_id == DEVICE_ID
        assert event.command_id == command_id
        assert event.command == "reboot-now"
        assert event.status == "received"
        assert event.error is None
    finally:
        subscription.close()


def test_failed_ack_publishes_the_error_message(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "sim-reset-now")
    subscription = command_ack_broadcaster.subscribe(user_id=1)
    try:
        test_client.post(
            HEARTBEAT_URL,
            json=_heartbeat_with_ack(
                DEVICE_HEADERS,
                {
                    "id": command_id,
                    "command": "sim-reset-now",
                    "status": "failed",
                    "error": "SIM not detected",
                },
            ),
            headers=DEVICE_HEADERS,
        )

        event = subscription.queue.get_nowait()
        assert event.status == "failed"
        assert event.error == "SIM not detected"
    finally:
        subscription.close()


def test_unrecognized_ack_status_publishes_nothing(test_client, db_session):
    # Contrast with the above: a status the backend doesn't know about at all is the one case
    # that's silently skipped, not just left non-terminal - see
    # test_unrecognized_ack_status_does_not_422_and_leaves_the_command_queued.
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "force-upload-now")
    subscription = command_ack_broadcaster.subscribe(user_id=1)
    try:
        test_client.post(
            HEARTBEAT_URL,
            json=_heartbeat_with_ack(
                DEVICE_HEADERS,
                {"id": command_id, "command": "force-upload-now", "status": "some-future-status"},
            ),
            headers=DEVICE_HEADERS,
        )

        assert subscription.queue.empty()
    finally:
        subscription.close()


# --- Stream auth boundary ---------------------------------------------------


def test_stream_requires_auth(test_client):
    response = test_client.get(STREAM_URL)

    assert response.status_code == 401


def test_stream_rejects_non_superuser(db_session, test_client):
    headers = _regular_user_headers(db_session, test_client)

    response = test_client.get(STREAM_URL, headers=headers)

    assert response.status_code == 403


def test_stream_over_the_per_user_cap_is_429(db_session, test_client):
    headers = _superuser_headers(db_session, test_client)
    user_id = db_session.query(User).one().id
    held = [command_ack_broadcaster.subscribe(user_id) for _ in range(5)]
    try:
        response = test_client.get(STREAM_URL, headers=headers)
    finally:
        for subscription in held:
            subscription.close()

    assert response.status_code == 429
