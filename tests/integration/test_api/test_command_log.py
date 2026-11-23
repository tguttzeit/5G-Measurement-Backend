"""Integration tests for the persisted command/override communication history:
rows written when a maintainer queues something and when a device acks a command, and
GET /command-log.
"""
import hashlib
import secrets

from fastapi_users.password import PasswordHelper
from sqlalchemy import select

from app.models import CommandLogEntry, Device, DeviceCommand
from app.models.user import User

password_helper = PasswordHelper()

DEVICE_ID = "cmdlog-device-01"
OTHER_DEVICE_ID = "cmdlog-device-02"
DEVICE_KEY = "correct-horse-battery-staple"
DEVICE_HEADERS = {"X-Device-ID": DEVICE_ID, "X-Device-Key": DEVICE_KEY}

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
    return _login_headers(db_session, test_client, "cmdlog-superuser", True)


def _log(test_client, headers, **params) -> list[dict]:
    response = test_client.get("/command-log", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["entries"]


def _queue_command(test_client, headers, command: str, device_id: str = DEVICE_ID) -> int:
    response = test_client.post(
        f"/devices/{device_id}/commands", json={"command": command}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["command_id"]


def _ack(test_client, command_id: int, command: str, status: str, error: str | None = None):
    ack = {"id": command_id, "command": command, "status": status}
    if error is not None:
        ack["error"] = error
    response = test_client.post(
        "/heartbeat",
        json={**VALID_HEARTBEAT_BODY, "executed_commands": [ack]},
        headers=DEVICE_HEADERS,
    )
    assert response.status_code == 200, response.text


def test_queueing_a_command_is_logged(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    command_id = _queue_command(test_client, headers, "force-upload-now")

    [entry] = _log(test_client, headers, device_id=DEVICE_ID)
    assert entry["direction"] == "to_device"
    assert entry["kind"] == "command"
    assert entry["name"] == "force-upload-now"
    assert entry["command_id"] == command_id
    assert entry["status"] == "queued"


def test_queueing_config_overrides_logs_one_row_per_field(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    response = test_client.post(
        f"/devices/{DEVICE_ID}/config-overrides",
        json={"movement_gate_movement_threshold": 100, "idle_threshold_s": 30},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    entries = _log(test_client, headers, device_id=DEVICE_ID)
    assert {(e["name"], e["detail"]) for e in entries} == {
        ("movement_gate_movement_threshold", "= 100.0"),
        ("idle_threshold_s", "= 30.0"),
    }
    assert all(e["kind"] == "config" and e["command_id"] is not None for e in entries)


def test_ack_is_logged_and_outlives_the_queue_row(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "sim-reset-now")

    _ack(test_client, command_id, "sim-reset-now", "failed", "modem not responding")

    queue = test_client.get(f"/devices/{DEVICE_ID}/queue", headers=headers).json()["queue"]
    assert queue == []
    newest, queued = _log(test_client, headers, device_id=DEVICE_ID)
    assert (newest["direction"], newest["status"], newest["detail"]) == (
        "from_device",
        "failed",
        "modem not responding",
    )
    assert newest["command_id"] == command_id
    assert queued["status"] == "queued"


def test_non_terminal_reboot_acks_are_each_logged(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "reboot-now")
    _heartbeat(test_client)

    _ack(test_client, command_id, "reboot-now", "received")
    _ack(test_client, command_id, "reboot-now", "success")

    statuses = [e["status"] for e in _log(test_client, headers, device_id=DEVICE_ID)]
    assert statuses == ["success", "received", "delivered", "queued"]  # newest first


def test_ack_for_unknown_command_is_not_logged(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    _ack(test_client, 999999, "force-upload-now", "success")

    assert _log(test_client, headers, device_id=DEVICE_ID) == []


def test_unrecognized_ack_status_is_not_logged(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "force-upload-now")

    _ack(test_client, command_id, "force-upload-now", "some-future-status")

    statuses = [e["status"] for e in _log(test_client, headers, device_id=DEVICE_ID)]
    assert statuses == ["delivered", "queued"]


def test_log_can_be_filtered_by_device_and_limited(test_client, db_session):
    _register_device(db_session)
    _register_device(db_session, OTHER_DEVICE_ID)
    headers = _superuser_headers(db_session, test_client)
    _queue_command(test_client, headers, "force-upload-now")
    _queue_command(test_client, headers, "reboot-now")
    _queue_command(test_client, headers, "force-upload-now", device_id=OTHER_DEVICE_ID)

    assert len(_log(test_client, headers)) == 3
    assert len(_log(test_client, headers, device_id=DEVICE_ID)) == 2
    assert len(_log(test_client, headers, limit=1)) == 1
    assert test_client.get("/command-log", params={"limit": 0}, headers=headers).status_code == 422


def test_log_requires_a_superuser(test_client, db_session):
    assert test_client.get("/command-log").status_code == 401
    regular = _login_headers(db_session, test_client, "cmdlog-regular", False)
    assert test_client.get("/command-log", headers=regular).status_code == 403


# --- delivered / removed events and the per-command status ------------------------------------


def _heartbeat(test_client, **extra):
    response = test_client.post(
        "/heartbeat", json={**VALID_HEARTBEAT_BODY, **extra}, headers=DEVICE_HEADERS
    )
    assert response.status_code == 200, response.text
    return response.json()


def _status(test_client, headers, device_id: str = DEVICE_ID) -> list[dict]:
    response = test_client.get(f"/devices/{device_id}/command-status", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _states(test_client, headers) -> dict[str, str]:
    return {item["name"]: item["state"] for item in _status(test_client, headers)}


def test_first_delivery_is_logged_once(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    _queue_command(test_client, headers, "force-upload-now")

    _heartbeat(test_client)
    _heartbeat(test_client)  # redelivery

    statuses = [e["status"] for e in _log(test_client, headers, device_id=DEVICE_ID)]
    assert statuses.count("delivered") == 1


def test_command_state_follows_its_lifecycle(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "force-upload-now")

    assert _states(test_client, headers) == {"force-upload-now": "queued"}
    _heartbeat(test_client)
    assert _states(test_client, headers) == {"force-upload-now": "delivered"}

    _ack(test_client, command_id, "force-upload-now", "success")
    [item] = _status(test_client, headers)
    assert (item["state"], item["complete"], item["in_queue"]) == ("success", True, False)
    assert item["queued_at"] and item["delivered_at"] and item["result_at"]


def test_failed_command_reports_its_error(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "sim-reset-now")

    _ack(test_client, command_id, "sim-reset-now", "failed", "modem not responding")

    [item] = _status(test_client, headers)
    assert (item["state"], item["error"]) == ("failed", "modem not responding")


def test_reboot_stays_open_after_received_until_its_success(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    reboot_id = _queue_command(test_client, headers, "reboot-now")

    _ack(test_client, reboot_id, "reboot-now", "received")
    [item] = _status(test_client, headers)
    assert (item["state"], item["complete"]) == ("received", False)

    _ack(test_client, reboot_id, "reboot-now", "success")
    assert _states(test_client, headers)["reboot-now"] == "success"


# --- shutdown-now is confirmed by the device going silent ----------------------


def _age_heartbeats(db_session, seconds: float) -> None:
    """Make everything the device sent so far look `seconds` older."""
    from datetime import timedelta

    from app.models import Heartbeat

    for heartbeat in db_session.scalars(select(Heartbeat)).all():
        heartbeat.received_at = heartbeat.received_at - timedelta(seconds=seconds)
    for entry in db_session.scalars(select(CommandLogEntry)).all():
        entry.occurred_at = entry.occurred_at - timedelta(seconds=seconds)
    db_session.commit()


def _shutdown_acked(test_client, db_session, headers, interval_s: float = 15) -> int:
    _register_device(db_session)
    command_id = _queue_command(test_client, headers, "shutdown-now")
    _heartbeat(test_client, current_config={"heartbeat_interval_s": interval_s})
    _ack(test_client, command_id, "shutdown-now", "received")
    return command_id


def test_shutdown_is_not_a_success_while_heartbeats_are_still_recent(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _shutdown_acked(test_client, db_session, headers)

    response = test_client.get(f"/devices/{DEVICE_ID}/command-status", headers=headers).json()

    [item] = response["items"]
    assert (item["state"], item["complete"], item["in_queue"]) == ("received", False, False)
    assert response["shutdown_confirm_mode"] == "intervals"
    assert response["shutdown_confirm_intervals"] == 4
    assert response["shutdown_confirm_seconds"] == 4 * 15
    assert response["shutdown_fail_heartbeats"] == 10
    assert response["heartbeat_interval_s"] == 15
    assert response["last_heartbeat_at"] is not None


def test_shutdown_succeeds_after_four_silent_intervals(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _shutdown_acked(test_client, db_session, headers, interval_s=15)

    _age_heartbeats(db_session, seconds=4 * 15 + 1)

    [item] = _status(test_client, headers)
    assert (item["state"], item["complete"]) == ("success", True)
    # The success is dated when the 4th interval ran out, not when someone looked.
    assert item["result_at"] is not None
    assert _states(test_client, headers) == {"shutdown-now": "success"}
    successes = [e for e in _log(test_client, headers) if e["status"] == "success"]
    assert len(successes) == 1


def test_a_confirmed_shutdown_reports_no_error(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _shutdown_acked(test_client, db_session, headers, interval_s=15)

    _age_heartbeats(db_session, seconds=4 * 15 + 1)

    [item] = _status(test_client, headers)
    assert (item["state"], item["error"]) == ("success", None)
    [success] = [e for e in _log(test_client, headers) if e["status"] == "success"]
    assert success["detail"] == "no heartbeat for 4 intervals"


def test_shutdown_is_not_confirmed_after_only_three_silent_intervals(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _shutdown_acked(test_client, db_session, headers, interval_s=15)

    _age_heartbeats(db_session, seconds=3 * 15 + 1)

    assert _states(test_client, headers) == {"shutdown-now": "received"}


def _set_shutdown_confirmation(test_client, headers, **setting) -> None:
    payload = {"mode": "intervals", "intervals": 4, "seconds": 60, **setting}
    response = test_client.put("/settings/shutdown-confirmation", json=payload, headers=headers)
    assert response.is_success


def test_configured_intervals_decide_when_a_shutdown_succeeds(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _set_shutdown_confirmation(test_client, headers, mode="intervals", intervals=2)
    _shutdown_acked(test_client, db_session, headers, interval_s=15)

    _age_heartbeats(db_session, seconds=2 * 15 - 1)
    assert _states(test_client, headers) == {"shutdown-now": "received"}

    _age_heartbeats(db_session, seconds=2)
    assert _states(test_client, headers) == {"shutdown-now": "success"}
    [success] = [e for e in _log(test_client, headers) if e["status"] == "success"]
    assert success["detail"] == "no heartbeat for 2 intervals"


def test_a_fixed_time_span_decides_when_a_shutdown_succeeds_regardless_of_the_interval(
    test_client, db_session
):
    headers = _superuser_headers(db_session, test_client)
    _set_shutdown_confirmation(test_client, headers, mode="seconds", seconds=100)
    _shutdown_acked(test_client, db_session, headers, interval_s=15)

    _age_heartbeats(db_session, seconds=99)  # past 4 intervals (60 s), still short of 100 s
    assert _states(test_client, headers) == {"shutdown-now": "received"}

    _age_heartbeats(db_session, seconds=2)
    assert _states(test_client, headers) == {"shutdown-now": "success"}
    [success] = [e for e in _log(test_client, headers) if e["status"] == "success"]
    assert success["detail"] == "no heartbeat for 100 s"


def test_status_reports_the_effective_rule_for_a_fixed_time_span(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _set_shutdown_confirmation(test_client, headers, mode="seconds", seconds=90)
    _shutdown_acked(test_client, db_session, headers, interval_s=15)

    response = test_client.get(f"/devices/{DEVICE_ID}/command-status", headers=headers).json()

    assert response["shutdown_confirm_mode"] == "seconds"
    assert response["shutdown_confirm_seconds"] == 90
    assert response["shutdown_confirm_intervals"] == 90 / 15


def test_a_returning_device_is_confirmed_with_the_configured_span(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _set_shutdown_confirmation(test_client, headers, mode="seconds", seconds=600)
    _shutdown_acked(test_client, db_session, headers, interval_s=15)
    _age_heartbeats(db_session, seconds=300)  # more than 4 intervals, less than 600 s

    _heartbeat(test_client)

    assert _states(test_client, headers) == {"shutdown-now": "received"}


def test_the_default_interval_applies_when_the_device_reports_none(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _register_device(db_session)
    command_id = _queue_command(test_client, headers, "shutdown-now")
    _ack(test_client, command_id, "shutdown-now", "received")

    response = test_client.get(f"/devices/{DEVICE_ID}/command-status", headers=headers).json()

    assert response["heartbeat_interval_s"] == 60


def test_a_device_that_comes_back_after_the_gap_still_gets_its_shutdown_confirmed(
    test_client, db_session
):
    headers = _superuser_headers(db_session, test_client)
    _shutdown_acked(test_client, db_session, headers, interval_s=15)
    _age_heartbeats(db_session, seconds=10 * 15)  # nobody opened the page while it was off

    _heartbeat(test_client)  # powered on again

    assert _states(test_client, headers) == {"shutdown-now": "success"}


def test_an_old_shutdown_ack_does_not_confirm_a_later_silence(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _shutdown_acked(test_client, db_session, headers, interval_s=15)
    # The device kept sending heartbeats well past the ack (so the shutdown evidently didn't
    # happen), then went quiet for other reasons.
    for _ in range(5):
        _age_heartbeats(db_session, seconds=15)
        _heartbeat(test_client, current_config={"heartbeat_interval_s": 15})
    _age_heartbeats(db_session, seconds=4 * 15 + 1)

    assert _states(test_client, headers) == {"shutdown-now": "received"}


def _heartbeats_after_ack(test_client, db_session, count: int) -> None:
    """Post `count` further heartbeats, each a few seconds after the previous one."""
    for _ in range(count):
        _age_heartbeats(db_session, seconds=3)
        _heartbeat(test_client, current_config={"heartbeat_interval_s": 15})


def test_shutdown_fails_when_the_device_is_still_sending_ten_heartbeats_later(
    test_client, db_session
):
    headers = _superuser_headers(db_session, test_client)
    _shutdown_acked(test_client, db_session, headers)

    _heartbeats_after_ack(test_client, db_session, 9)
    assert _states(test_client, headers) == {"shutdown-now": "received"}

    _heartbeats_after_ack(test_client, db_session, 1)
    [item] = _status(test_client, headers)
    assert (item["state"], item["complete"]) == ("failed", True)
    assert "still sending heartbeats" in item["error"]
    failures = [e for e in _log(test_client, headers) if e["status"] == "failed"]
    assert len(failures) == 1

    _heartbeats_after_ack(test_client, db_session, 2)  # no second failure event
    assert len([e for e in _log(test_client, headers) if e["status"] == "failed"]) == 1


def test_the_ack_heartbeat_itself_is_not_counted_towards_the_failure(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _shutdown_acked(test_client, db_session, headers)

    _heartbeats_after_ack(test_client, db_session, 8)  # + the ack heartbeat would make 9, not 10

    assert _states(test_client, headers) == {"shutdown-now": "received"}


# --- the device reports a shutdown-now's success after booting again --------------------------


def _results(test_client, headers, status: str) -> list[dict]:
    return [e for e in _log(test_client, headers) if e["status"] == status]


def test_a_success_after_the_next_boot_resolves_a_shutdown_without_a_queue_row(
    test_client, db_session
):
    headers = _superuser_headers(db_session, test_client)
    command_id = _shutdown_acked(test_client, db_session, headers)

    _ack(test_client, command_id, "shutdown-now", "success")

    [item] = _status(test_client, headers)
    assert (item["state"], item["error"], item["in_queue"]) == ("success", None, False)
    [success] = _results(test_client, headers, "success")
    assert success["command_id"] == command_id


def test_a_late_shutdown_success_wins_over_a_later_inferred_failure(test_client, db_session):
    # Powered on again inside the silence window: the heartbeats keep coming, so without the
    # device's own success the backend would count them up to a failure.
    headers = _superuser_headers(db_session, test_client)
    command_id = _shutdown_acked(test_client, db_session, headers)
    _heartbeats_after_ack(test_client, db_session, 2)

    _ack(test_client, command_id, "shutdown-now", "success")
    _heartbeats_after_ack(test_client, db_session, 10)

    assert _states(test_client, headers) == {"shutdown-now": "success"}
    assert _results(test_client, headers, "failed") == []


def test_a_repeated_late_shutdown_success_is_logged_once(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    command_id = _shutdown_acked(test_client, db_session, headers)

    _ack(test_client, command_id, "shutdown-now", "success")
    _ack(test_client, command_id, "shutdown-now", "success")

    assert len(_results(test_client, headers, "success")) == 1


def test_a_late_success_does_not_replace_an_inferred_shutdown_result(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    command_id = _shutdown_acked(test_client, db_session, headers)
    _heartbeats_after_ack(test_client, db_session, 10)

    _ack(test_client, command_id, "shutdown-now", "success")

    assert _states(test_client, headers) == {"shutdown-now": "failed"}
    assert _results(test_client, headers, "success") == []


def test_only_a_late_success_resolves_a_shutdown_without_a_queue_row(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    command_id = _shutdown_acked(test_client, db_session, headers)

    _ack(test_client, command_id, "shutdown-now", "failed", "made up")
    _ack(test_client, command_id, "shutdown-now", "not_applicable")

    assert _states(test_client, headers) == {"shutdown-now": "received"}


def test_another_device_cannot_report_the_success_of_a_shutdown(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    command_id = _shutdown_acked(test_client, db_session, headers)
    _register_device(db_session, OTHER_DEVICE_ID)

    response = test_client.post(
        "/heartbeat",
        json={
            **VALID_HEARTBEAT_BODY,
            "executed_commands": [
                {"id": command_id, "command": "shutdown-now", "status": "success"}
            ],
        },
        headers={"X-Device-ID": OTHER_DEVICE_ID, "X-Device-Key": DEVICE_KEY},
    )
    assert response.status_code == 200, response.text

    assert _states(test_client, headers) == {"shutdown-now": "received"}
    assert _results(test_client, headers, "success") == []


def test_a_success_without_a_queue_row_is_ignored_for_other_commands(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _register_device(db_session)
    reboot_id = _queue_command(test_client, headers, "reboot-now")
    _ack(test_client, reboot_id, "reboot-now", "success")
    removed_id = _queue_command(test_client, headers, "shutdown-now")
    test_client.delete(f"/devices/{DEVICE_ID}/queue/{removed_id}", headers=headers)

    _ack(test_client, reboot_id, "reboot-now", "success")
    _ack(test_client, removed_id, "shutdown-now", "success")

    assert _states(test_client, headers) == {"reboot-now": "success", "shutdown-now": "removed"}
    assert len(_results(test_client, headers, "success")) == 1


def test_removed_command_is_reported_as_removed(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    first = _queue_command(test_client, headers, "force-upload-now")
    _queue_command(test_client, headers, "reboot-now")

    test_client.delete(f"/devices/{DEVICE_ID}/queue/{first}", headers=headers)
    assert _states(test_client, headers) == {"force-upload-now": "removed", "reboot-now": "queued"}

    test_client.delete(f"/devices/{DEVICE_ID}/queue", headers=headers)
    assert _states(test_client, headers) == {"force-upload-now": "removed", "reboot-now": "removed"}
    [removed_entry] = [
        e for e in _log(test_client, headers, device_id=DEVICE_ID) if e["name"] == "reboot-now"
        and e["status"] == "removed"
    ]
    assert removed_entry["direction"] == "to_device"


def test_command_queued_before_the_log_existed_still_shows_up(test_client, db_session):
    from app.models import CommandType, DeviceCommand

    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    db_session.add(
        DeviceCommand(
            device_id=DEVICE_ID,
            type=CommandType.ONE_SHOT,
            payload={"command": "mode-manual-now"},
        )
    )
    db_session.commit()

    [item] = _status(test_client, headers)
    assert (item["name"], item["state"]) == ("mode-manual-now", "queued")
    assert item["queued_at"] is not None


def test_config_override_is_applied_once_the_device_reports_the_value(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    test_client.post(
        f"/devices/{DEVICE_ID}/config-overrides", json={"heartbeat_interval_s": 15}, headers=headers
    )
    assert _states(test_client, headers) == {"heartbeat_interval_s": "queued"}

    # Delivered; the device's own current_config can't reflect it yet.
    _heartbeat(test_client, current_config={"heartbeat_interval_s": 30})
    assert _states(test_client, headers) == {"heartbeat_interval_s": "delivered"}
    _heartbeat(test_client, current_config={"heartbeat_interval_s": 30})
    assert _states(test_client, headers) == {"heartbeat_interval_s": "delivered"}

    _heartbeat(test_client, current_config={"heartbeat_interval_s": 15.0})
    [item] = _status(test_client, headers)
    assert (item["state"], item["complete"]) == ("success", True)

    _heartbeat(test_client, current_config={"heartbeat_interval_s": 15})
    applied = [
        e for e in _log(test_client, headers, device_id=DEVICE_ID) if e["status"] == "success"
    ]
    assert len(applied) == 1


def test_requeueing_an_override_restarts_its_lifecycle(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    url = f"/devices/{DEVICE_ID}/config-overrides"
    test_client.post(url, json={"idle_threshold_s": 60}, headers=headers)
    _heartbeat(test_client)
    _heartbeat(test_client, current_config={"idle_threshold_s": 60})
    assert _states(test_client, headers) == {"idle_threshold_s": "success"}

    test_client.post(url, json={"idle_threshold_s": 90}, headers=headers)

    assert _states(test_client, headers) == {"idle_threshold_s": "queued"}
    _heartbeat(test_client, current_config={"idle_threshold_s": 60})
    assert _states(test_client, headers) == {"idle_threshold_s": "delivered"}


def test_status_is_limited_and_newest_first(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    for command in ("force-upload-now", "reboot-now", "sim-reset-now"):
        _queue_command(test_client, headers, command)

    response = test_client.get(
        f"/devices/{DEVICE_ID}/command-status", params={"limit": 2}, headers=headers
    )

    assert [i["name"] for i in response.json()["items"]] == ["sim-reset-now", "reboot-now"]


def test_status_requires_a_superuser_and_a_known_device(test_client, db_session):
    _register_device(db_session)
    regular = _login_headers(db_session, test_client, "cmdlog-regular-2", False)
    assert test_client.get(f"/devices/{DEVICE_ID}/command-status").status_code == 401
    assert (
        test_client.get(f"/devices/{DEVICE_ID}/command-status", headers=regular).status_code == 403
    )
    headers = _superuser_headers(db_session, test_client)
    assert test_client.get("/devices/nope/command-status", headers=headers).status_code == 404


def test_promoting_overrides_ends_their_timeline_as_promoted(test_client, db_session):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    test_client.post(
        f"/devices/{DEVICE_ID}/config-overrides", json={"idle_threshold_s": 60}, headers=headers
    )
    _queue_command(test_client, headers, "promote-overrides-now")

    _heartbeat(test_client)  # delivers the override and the promotion; the override row is cleared

    states = _states(test_client, headers)
    assert states["idle_threshold_s"] == "promoted"
    [item] = [i for i in _status(test_client, headers) if i["name"] == "idle_threshold_s"]
    assert (item["complete"], item["in_queue"]) == (True, False)
    assert item["promoted_at"] is not None


def test_expired_command_is_cleaned_up_and_logged_with_its_expiry_time(test_client, db_session):
    from datetime import UTC, datetime, timedelta

    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    command_id = _queue_command(test_client, headers, "force-upload-now")
    expires_at = datetime.now(UTC) - timedelta(hours=1)
    row = db_session.get(DeviceCommand, command_id)
    row.expires_at = expires_at
    # Make the queueing look like it happened 24h before the expiry, as it would for real.
    queued_event = db_session.scalars(
        select(CommandLogEntry).where(CommandLogEntry.command_id == command_id)
    ).one()
    queued_event.occurred_at = expires_at - timedelta(hours=24)
    db_session.commit()

    body = _heartbeat(test_client)

    assert "commands" not in body  # not delivered
    db_session.expire_all()
    assert db_session.get(DeviceCommand, command_id) is None
    [item] = _status(test_client, headers)
    assert (item["state"], item["complete"]) == ("expired", True)
    assert datetime.fromisoformat(item["expired_at"]) == expires_at
    assert _states(test_client, headers) == {"force-upload-now": "expired"}
