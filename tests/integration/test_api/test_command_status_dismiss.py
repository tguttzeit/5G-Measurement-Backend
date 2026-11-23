"""Integration tests for "Delete shown" on the command status timelines:
POST /devices/{id}/command-status/dismiss hides finished commands from
GET /devices/{id}/command-status without touching the command log.
"""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi_users.password import PasswordHelper

from app.models import CommandLogEntry, CommandStatusDismissal, Device, DeviceCommand
from app.models.user import User

password_helper = PasswordHelper()

DEVICE_ID = "dismiss-device-01"
OTHER_DEVICE_ID = "dismiss-device-02"
DEVICE_KEY = "correct-horse-battery-staple"

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


def _login_headers(db_session, test_client, email: str, is_superuser: bool) -> dict:
    db_session.add(
        User(
            email=email,
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=is_superuser,
            is_verified=False,
        )
    )
    db_session.commit()
    response = test_client.post(
        "/auth/login", data={"username": email, "password": "correct-horse-battery-staple"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _superuser_headers(db_session, test_client) -> dict:
    return _login_headers(db_session, test_client, "dismiss-superuser", True)


def _queue_command(test_client, headers, command: str, device_id: str = DEVICE_ID) -> int:
    response = test_client.post(
        f"/devices/{device_id}/commands", json={"command": command}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["command_id"]


def _finish(test_client, command_id: int, command: str, status: str = "success") -> None:
    """The device acks the command, which also clears its queue row."""
    response = test_client.post(
        "/heartbeat",
        json={
            **VALID_HEARTBEAT_BODY,
            "executed_commands": [{"id": command_id, "command": command, "status": status}],
        },
        headers={"X-Device-ID": DEVICE_ID, "X-Device-Key": DEVICE_KEY},
    )
    assert response.status_code == 200, response.text


def _queue_finished_command(test_client, headers, command: str = "force-upload-now") -> int:
    command_id = _queue_command(test_client, headers, command)
    _finish(test_client, command_id, command)
    return command_id


def _status_ids(test_client, headers, device_id: str = DEVICE_ID, **params) -> list[int]:
    response = test_client.get(
        f"/devices/{device_id}/command-status", params=params, headers=headers
    )
    assert response.status_code == 200, response.text
    return [item["command_id"] for item in response.json()["items"]]


def _dismiss(test_client, headers, command_ids, device_id: str = DEVICE_ID):
    return test_client.post(
        f"/devices/{device_id}/command-status/dismiss",
        json={"command_ids": command_ids},
        headers=headers,
    )


def test_dismissing_a_finished_command_hides_it_from_the_status(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    finished = _queue_finished_command(test_client, headers)
    kept = _queue_finished_command(test_client, headers, "reboot-now")

    response = _dismiss(test_client, headers, [finished])

    assert response.status_code == 200, response.text
    assert response.json() == {"dismissed": [finished]}
    assert _status_ids(test_client, headers) == [kept]


def test_in_progress_commands_are_never_dismissed(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    queued = _queue_command(test_client, headers, "force-upload-now")
    finished = _queue_finished_command(test_client, headers, "reboot-now")

    response = _dismiss(test_client, headers, [queued, finished])

    assert response.json() == {"dismissed": [finished]}
    assert _status_ids(test_client, headers) == [queued]


def test_a_received_command_that_is_still_in_the_queue_is_not_dismissed(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "reboot-now")
    _finish(test_client, command_id, "reboot-now", status="received")

    response = _dismiss(test_client, headers, [command_id])

    assert response.json() == {"dismissed": []}
    assert _status_ids(test_client, headers) == [command_id]


def test_an_applied_config_override_stays_in_the_queue_and_is_not_dismissed(
    test_client, db_session
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    response = test_client.post(
        f"/devices/{DEVICE_ID}/config-overrides",
        json={"idle_threshold_s": 30},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    override = db_session.query(DeviceCommand).filter_by(device_id=DEVICE_ID).one()
    db_session.add(
        CommandLogEntry(
            device_id=DEVICE_ID,
            direction="from_device",
            kind="config",
            name="idle_threshold_s",
            command_id=override.id,
            status="success",
        )
    )
    db_session.commit()

    response = _dismiss(test_client, headers, [override.id])

    assert response.json() == {"dismissed": []}
    assert _status_ids(test_client, headers) == [override.id]


def test_a_removed_command_counts_as_finished(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "force-upload-now")
    response = test_client.delete(f"/devices/{DEVICE_ID}/queue/{command_id}", headers=headers)
    assert response.status_code == 200, response.text

    response = _dismiss(test_client, headers, [command_id])

    assert response.json() == {"dismissed": [command_id]}
    assert _status_ids(test_client, headers) == []


def test_ids_of_another_device_or_unknown_ids_are_ignored(test_client, db_session):
    _register_device(db_session)
    _register_device(db_session, OTHER_DEVICE_ID)
    headers = _superuser_headers(db_session, test_client)
    other = _queue_command(test_client, headers, "force-upload-now", OTHER_DEVICE_ID)
    response = test_client.delete(f"/devices/{OTHER_DEVICE_ID}/queue/{other}", headers=headers)
    assert response.status_code == 200, response.text

    response = _dismiss(test_client, headers, [other, 999_999])

    assert response.status_code == 200, response.text
    assert response.json() == {"dismissed": []}
    assert _status_ids(test_client, headers, OTHER_DEVICE_ID) == [other]


def test_dismissing_is_idempotent(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_finished_command(test_client, headers)

    first = _dismiss(test_client, headers, [command_id])
    second = _dismiss(test_client, headers, [command_id, command_id])

    assert first.json() == second.json() == {"dismissed": [command_id]}
    assert _status_ids(test_client, headers) == []
    assert db_session.query(CommandStatusDismissal).filter_by(device_id=DEVICE_ID).count() == 1


def test_a_command_with_activity_after_the_dismissal_shows_up_again(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_finished_command(test_client, headers)
    assert _dismiss(test_client, headers, [command_id]).json() == {"dismissed": [command_id]}
    assert _status_ids(test_client, headers) == []

    # A re-queue of the same id (a config override reuses its row) restarts its lifecycle.
    db_session.add(
        CommandLogEntry(
            device_id=DEVICE_ID,
            direction="to_device",
            kind="command",
            name="force-upload-now",
            command_id=command_id,
            status="queued",
            occurred_at=datetime.now(UTC) + timedelta(minutes=1),
        )
    )
    db_session.commit()

    assert _status_ids(test_client, headers) == [command_id]


def test_dismissed_commands_do_not_use_up_limit_slots(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    oldest = _queue_finished_command(test_client, headers, "force-upload-now")
    middle = _queue_finished_command(test_client, headers, "reboot-now")
    newest = _queue_finished_command(test_client, headers, "stop-measuring-now")
    assert _status_ids(test_client, headers, limit=2) == [newest, middle]

    _dismiss(test_client, headers, [newest])

    assert _status_ids(test_client, headers, limit=2) == [middle, oldest]


def test_the_command_log_is_untouched(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_finished_command(test_client, headers)
    before = test_client.get("/command-log", headers=headers).json()

    _dismiss(test_client, headers, [command_id])

    assert test_client.get("/command-log", headers=headers).json() == before
    assert before["entries"]


def test_dismissing_requires_a_superuser(test_client, db_session):
    _register_device(db_session)
    command_id = _queue_finished_command(test_client, _superuser_headers(db_session, test_client))
    user_headers = _login_headers(db_session, test_client, "dismiss-plain-user", False)

    assert _dismiss(test_client, user_headers, [command_id]).status_code == 403
    assert _dismiss(test_client, {}, [command_id]).status_code == 401


def test_dismissing_for_an_unknown_device_is_404(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    assert _dismiss(test_client, headers, [1], device_id="no-such-device").status_code == 404


def test_the_request_body_is_validated(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    def dismiss(body):
        return test_client.post(
            f"/devices/{DEVICE_ID}/command-status/dismiss", json=body, headers=headers
        )

    assert dismiss({"command_ids": []}).status_code == 422
    assert dismiss({"command_ids": [0]}).status_code == 422
    assert dismiss({"command_ids": [-3]}).status_code == 422
    assert dismiss({"command_ids": ["1"]}).status_code == 422
    assert dismiss({"command_ids": list(range(1, 502))}).status_code == 422
    assert dismiss({"command_ids": [1], "device_id": "other"}).status_code == 422
    assert dismiss({}).status_code == 422
