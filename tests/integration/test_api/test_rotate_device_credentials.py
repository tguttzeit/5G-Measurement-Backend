"""scripts/rotate_device_credentials.py: new key and secret replace the old ones immediately."""
import hashlib
import hmac
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Device
from app.models.commands import CommandType, DeviceCommand
from app.response_signing import sign_heartbeat_response
from scripts import rotate_device_credentials
from scripts.rotate_device_credentials import UnknownDeviceError, rotate_credentials

DEVICE_ID = "rotate-test-01"
OLD_KEY = "old-device-key"
OLD_HMAC_SECRET = "old-hmac-secret"

VALID_HEARTBEAT_BODY = {
    "since_run_start": {"datapoints_total": 1, "good": 1, "bad": 0, "invalid": 0},
    "pipeline_broken": False,
    "storage": {"pending_files": 0, "disk_free_bytes": 10**9},
}


def _register_device(db_session) -> None:
    db_session.add(
        Device(
            device_id=DEVICE_ID,
            api_key_hash=hashlib.sha256(OLD_KEY.encode()).hexdigest(),
            hmac_secret=OLD_HMAC_SECRET,
        )
    )
    db_session.commit()


def _heartbeat(test_client, device_key: str):
    return test_client.post(
        "/heartbeat",
        json=VALID_HEARTBEAT_BODY,
        headers={"X-Device-ID": DEVICE_ID, "X-Device-Key": device_key},
    )


def _signed_with(secret: str, response_body: dict) -> bool:
    body = dict(response_body)
    signature = body.pop("signature")
    expected = sign_heartbeat_response(Device(hmac_secret=secret), body)
    return hmac.compare_digest(signature, expected)


def test_old_key_is_rejected_and_new_key_accepted(test_client, db_session):
    _register_device(db_session)

    new_key, _ = rotate_credentials(db_session, DEVICE_ID)

    assert _heartbeat(test_client, OLD_KEY).status_code == 401
    assert _heartbeat(test_client, new_key).status_code == 200


def test_new_values_are_random_and_only_the_key_hash_is_stored(db_session):
    _register_device(db_session)

    new_key, new_hmac_secret = rotate_credentials(db_session, DEVICE_ID)

    assert len(new_key) == 64 and len(new_hmac_secret) == 64
    assert new_key != new_hmac_secret
    db_session.expire_all()
    device = db_session.get(Device, DEVICE_ID)
    assert device.api_key_hash == hashlib.sha256(new_key.encode()).hexdigest()
    assert device.hmac_secret == new_hmac_secret


def test_queued_command_is_delivered_and_signed_with_the_new_secret(test_client, db_session):
    _register_device(db_session)
    db_session.add(
        DeviceCommand(
            device_id=DEVICE_ID,
            type=CommandType.ONE_SHOT,
            payload={"command": "force-upload-now"},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db_session.commit()

    new_key, new_hmac_secret = rotate_credentials(db_session, DEVICE_ID)
    response = _heartbeat(test_client, new_key)

    assert [c["command"] for c in response.json()["commands"]] == ["force-upload-now"]
    assert _signed_with(new_hmac_secret, response.json())
    assert not _signed_with(OLD_HMAC_SECRET, response.json())


def test_unknown_device_raises_and_creates_nothing(db_session):
    with pytest.raises(UnknownDeviceError):
        rotate_credentials(db_session, "no-such-device")

    assert db_session.get(Device, "no-such-device") is None


def _use_test_session(monkeypatch, db_session) -> None:
    @contextmanager
    def session_bound_to_test_db():
        yield db_session

    monkeypatch.setattr(rotate_device_credentials, "_open_session", session_bound_to_test_db)


def test_main_prints_both_new_values_once(monkeypatch, capsys, db_session):
    _register_device(db_session)
    _use_test_session(monkeypatch, db_session)
    monkeypatch.setattr(sys, "argv", ["rotate_device_credentials.py", DEVICE_ID])

    rotate_device_credentials.main()

    out = capsys.readouterr().out
    db_session.expire_all()
    device = db_session.get(Device, DEVICE_ID)
    assert out.count(device.hmac_secret) == 1
    printed_key = next(
        line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("API Key: ")
    )
    assert hashlib.sha256(printed_key.encode()).hexdigest() == device.api_key_hash
    assert out.count(printed_key) == 1


def test_main_exits_with_error_for_unknown_device(monkeypatch, capsys, db_session):
    _use_test_session(monkeypatch, db_session)
    monkeypatch.setattr(sys, "argv", ["rotate_device_credentials.py", "no-such-device"])

    with pytest.raises(SystemExit) as exit_info:
        rotate_device_credentials.main()

    assert exit_info.value.code == 1
    assert "no-such-device" in capsys.readouterr().err
