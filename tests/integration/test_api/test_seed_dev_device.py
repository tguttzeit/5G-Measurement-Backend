"""scripts/seed_dev_device.py: a device with fixed credentials that can actually authenticate."""
import sys
from types import SimpleNamespace

import pytest

from app.models import Device
from scripts import seed_dev_device
from scripts.seed_dev_device import seed_device

VALID_HEARTBEAT_BODY = {
    "since_run_start": {"datapoints_total": 1, "good": 1, "bad": 0, "invalid": 0},
    "pipeline_broken": False,
    "storage": {"pending_files": 0, "disk_free_bytes": 10**9},
}


def _heartbeat(test_client, device_id: str, device_key: str):
    return test_client.post(
        "/heartbeat",
        json=VALID_HEARTBEAT_BODY,
        headers={"X-Device-ID": device_id, "X-Device-Key": device_key},
    )


def test_seeded_device_authenticates_with_the_given_key(test_client, db_session):
    created = seed_device(db_session, "seed-dev-01", "known-key", "known-hmac")

    assert created is True
    assert _heartbeat(test_client, "seed-dev-01", "known-key").status_code == 200
    assert _heartbeat(test_client, "seed-dev-01", "other-key").status_code == 401
    assert db_session.get(Device, "seed-dev-01").hmac_secret == "known-hmac"


def test_seeding_again_resets_the_credentials(test_client, db_session):
    seed_device(db_session, "seed-dev-02", "first-key", "first-hmac")

    created = seed_device(db_session, "seed-dev-02", "second-key", "second-hmac")

    assert created is False
    assert _heartbeat(test_client, "seed-dev-02", "first-key").status_code == 401
    assert _heartbeat(test_client, "seed-dev-02", "second-key").status_code == 200
    db_session.expire_all()
    assert db_session.get(Device, "seed-dev-02").hmac_secret == "second-hmac"


def test_refuses_to_run_in_production(monkeypatch, capsys):
    monkeypatch.setattr(
        seed_dev_device, "get_settings", lambda: SimpleNamespace(environment="production")
    )
    monkeypatch.setattr(sys, "argv", ["seed_dev_device.py"])

    with pytest.raises(SystemExit) as exit_info:
        seed_dev_device.main()

    assert exit_info.value.code == 1
    assert "Refusing" in capsys.readouterr().err
