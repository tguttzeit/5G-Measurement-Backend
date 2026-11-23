"""Integration tests for heartbeat ingestion and retrieval.

Full round trip against a real Postgres (tests/integration/conftest.py) - registers a real
device and, for the dashboard-facing GET endpoints, a real superuser (mirroring
test_admin_users.py / test_commands.py). Covers what tests/unit/test_heartbeat.py can only
assert without a database: persistence, the response's HMAC signature, and the dashboard
listing/detail endpoints. Command/config-override delivery via the heartbeat response is
covered in test_commands.py and isn't duplicated here.
"""
import hashlib
import secrets

import pytest
from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device, Heartbeat
from app.models.user import User

password_helper = PasswordHelper()

HEARTBEAT_URL = "/heartbeat"

KNOWN_DEVICE_ID = "heartbeat-test-device-01"
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


# --- Device auth boundary --------------------------------------------------


def test_heartbeat_requires_device_id_header(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers={"X-Device-Key": KNOWN_DEVICE_KEY}
    )

    assert response.status_code == 401


def test_heartbeat_requires_device_key_header(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(
        HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers={"X-Device-ID": KNOWN_DEVICE_ID}
    )

    assert response.status_code == 401


def test_heartbeat_rejects_unknown_device_id(test_client: TestClient, db_session: Session):
    response = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert response.status_code == 401


def test_heartbeat_rejects_wrong_device_key(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(
        HEARTBEAT_URL,
        json=VALID_HEARTBEAT_BODY,
        headers={"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": "wrong-key"},
    )

    assert response.status_code == 401


# --- Valid heartbeat --------------------------------------------------


def test_valid_heartbeat_is_persisted(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    stored = db_session.scalars(
        select(Heartbeat).where(Heartbeat.device_id == KNOWN_DEVICE_ID)
    ).one()
    assert stored.datapoints_total == 100
    assert stored.datapoints_valid == 95
    assert stored.datapoints_invalid == 5
    assert stored.pipeline_broken is False
    assert stored.storage_pending_files == 3
    assert stored.storage_disk_free_bytes == 50000000000


def test_valid_heartbeat_response_is_hmac_signed(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    body = response.json()
    assert body["status"] == "ok"
    assert body["signature"].startswith("hmac-sha256:")


def test_current_config_is_persisted_when_present(test_client: TestClient, db_session: Session):
    _register_device(db_session)
    current_config = {"rsrp_threshold": -100.0, "heartbeat_interval_s": 60.0}
    body = {**VALID_HEARTBEAT_BODY, "current_config": current_config}

    response = test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    stored = db_session.scalars(
        select(Heartbeat).where(Heartbeat.device_id == KNOWN_DEVICE_ID)
    ).one()
    assert stored.current_config == current_config


def test_current_config_is_none_when_omitted(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    stored = db_session.scalars(
        select(Heartbeat).where(Heartbeat.device_id == KNOWN_DEVICE_ID)
    ).one()
    assert stored.current_config is None


def test_oversized_current_config_is_rejected(test_client: TestClient, db_session: Session):
    _register_device(db_session)
    body = {**VALID_HEARTBEAT_BODY, "current_config": {"blob": "x" * 10_000}}

    response = test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)

    assert response.status_code == 413
    assert db_session.scalars(select(Heartbeat)).all() == []


def test_repeated_heartbeats_accumulate_rows(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)
    test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    stored = db_session.scalars(
        select(Heartbeat).where(Heartbeat.device_id == KNOWN_DEVICE_ID)
    ).all()
    assert len(stored) == 2


# --- Invalid payload ----------------------------------------------------


def test_heartbeat_rejects_missing_required_field(test_client: TestClient, db_session: Session):
    _register_device(db_session)
    malformed = {k: v for k, v in VALID_HEARTBEAT_BODY.items() if k != "storage"}

    response = test_client.post(HEARTBEAT_URL, json=malformed, headers=DEVICE_HEADERS)

    assert response.status_code == 422
    assert db_session.scalars(select(Heartbeat)).all() == []


# --- Dashboard listing/detail (maintainer-facing, JWT-gated) --------------


def test_get_latest_heartbeats_requires_auth(test_client: TestClient, db_session: Session):
    response = test_client.get(HEARTBEAT_URL)

    assert response.status_code == 401


def test_get_device_heartbeat_returns_404_when_none_exists(
    test_client: TestClient, db_session: Session
):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.get(f"{HEARTBEAT_URL}/no-such-device", headers=headers)

    assert response.status_code == 404


def test_get_latest_heartbeats_reflects_most_recent_per_device(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)
    second_body = {
        **VALID_HEARTBEAT_BODY,
        "since_run_start": {"datapoints_total": 200, "good": 180, "bad": 15, "invalid": 5},
    }
    test_client.post(HEARTBEAT_URL, json=second_body, headers=DEVICE_HEADERS)

    response = test_client.get(HEARTBEAT_URL, headers=headers)

    assert response.status_code == 200
    summaries = response.json()["heartbeats"]
    assert len(summaries) == 1
    assert summaries[0]["device_id"] == KNOWN_DEVICE_ID
    assert summaries[0]["datapoints_total"] == 200


def test_get_device_heartbeat_returns_latest_summary(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)

    test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    response = test_client.get(f"{HEARTBEAT_URL}/{KNOWN_DEVICE_ID}", headers=headers)

    assert response.status_code == 200
    assert response.json()["device_id"] == KNOWN_DEVICE_ID
    assert response.json()["datapoints_total"] == 100


# --- current_config visibility --------------------------------


def _regular_user_headers(
    db_session: Session, test_client: TestClient, username: str = "regular-user"
) -> dict:
    db_session.add(
        User(
            email=username,
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
    )
    db_session.commit()
    return {"Authorization": f"Bearer {_login(test_client, username)}"}


def test_get_device_heartbeat_includes_current_config_for_superuser(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    body = {**VALID_HEARTBEAT_BODY, "current_config": {"rsrp_threshold": -100.0}}
    test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)

    response = test_client.get(f"{HEARTBEAT_URL}/{KNOWN_DEVICE_ID}", headers=headers)

    assert response.json()["current_config"] == {"rsrp_threshold": -100.0}


def test_get_device_heartbeat_hides_current_config_for_regular_user(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    body = {**VALID_HEARTBEAT_BODY, "current_config": {"rsrp_threshold": -100.0}}
    test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)
    headers = _regular_user_headers(db_session, test_client)

    response = test_client.get(f"{HEARTBEAT_URL}/{KNOWN_DEVICE_ID}", headers=headers)

    assert response.status_code == 200
    assert response.json()["current_config"] is None


def test_get_latest_heartbeats_includes_current_config_for_superuser(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    body = {**VALID_HEARTBEAT_BODY, "current_config": {"rsrp_threshold": -100.0}}
    test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)

    response = test_client.get(HEARTBEAT_URL, headers=headers)

    assert response.json()["heartbeats"][0]["current_config"] == {"rsrp_threshold": -100.0}


def test_get_latest_heartbeats_hides_current_config_for_regular_user(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    body = {**VALID_HEARTBEAT_BODY, "current_config": {"rsrp_threshold": -100.0}}
    test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)
    headers = _regular_user_headers(db_session, test_client)

    response = test_client.get(HEARTBEAT_URL, headers=headers)

    assert response.status_code == 200
    assert response.json()["heartbeats"][0]["current_config"] is None


# --- run_phase / gps_fix ---------------------------------------


def test_run_phase_and_gps_fix_are_persisted_when_present(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    body = {
        **VALID_HEARTBEAT_BODY,
        "run_phase": "active_measuring",
        "gps_fix": {"has_fix": True, "num_satellites": 8, "fix_age_s": 1.5},
    }

    response = test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    stored = db_session.scalars(
        select(Heartbeat).where(Heartbeat.device_id == KNOWN_DEVICE_ID)
    ).one()
    assert stored.run_phase == "active_measuring"
    assert stored.gps_fix == {"has_fix": True, "num_satellites": 8, "fix_age_s": 1.5}


def test_run_phase_and_gps_fix_are_none_when_omitted(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    response = test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    stored = db_session.scalars(
        select(Heartbeat).where(Heartbeat.device_id == KNOWN_DEVICE_ID)
    ).one()
    assert stored.run_phase is None
    assert stored.gps_fix is None


def test_heartbeat_rejects_invalid_run_phase(test_client: TestClient, db_session: Session):
    _register_device(db_session)
    body = {**VALID_HEARTBEAT_BODY, "run_phase": "not_a_real_phase"}

    response = test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)

    assert response.status_code == 422
    assert db_session.scalars(select(Heartbeat)).all() == []


def test_heartbeat_rejects_out_of_bounds_gps_fix(test_client: TestClient, db_session: Session):
    _register_device(db_session)
    body = {**VALID_HEARTBEAT_BODY, "gps_fix": {"has_fix": True, "num_satellites": -1}}

    response = test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)

    assert response.status_code == 422
    assert db_session.scalars(select(Heartbeat)).all() == []


def test_get_device_heartbeat_includes_run_phase_and_gps_fix_for_any_authenticated_user(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    body = {
        **VALID_HEARTBEAT_BODY,
        "run_phase": "waiting_for_gps_fix",
        "gps_fix": {"has_fix": False, "num_satellites": None, "fix_age_s": None},
    }
    test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)
    headers = _regular_user_headers(db_session, test_client)

    response = test_client.get(f"{HEARTBEAT_URL}/{KNOWN_DEVICE_ID}", headers=headers)

    assert response.status_code == 200
    assert response.json()["run_phase"] == "waiting_for_gps_fix"
    assert response.json()["gps_fix"] == {
        "has_fix": False,
        "num_satellites": None,
        "fix_age_s": None,
    }


# --- critical_error / system_mode ------------------------------

CRITICAL_ERROR = {
    "fingerprint": "gps_reader.read_fix:TimeoutError",
    "same_error_count": 3,
    "consecutive_reboots": 2,
    "action": "maintenance_mode",
}
CRITICAL_ERROR_BODY = {
    **VALID_HEARTBEAT_BODY,
    "run_phase": "critical_error",
    "critical_error": CRITICAL_ERROR,
    "current_config": {"system_mode": "auto", "rsrp_threshold": -100.0},
}


def test_critical_error_heartbeat_is_accepted_and_stored(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    response = test_client.post(HEARTBEAT_URL, json=CRITICAL_ERROR_BODY, headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    stored = db_session.scalars(select(Heartbeat)).one()
    assert stored.run_phase == "critical_error"
    assert stored.critical_error == CRITICAL_ERROR


@pytest.mark.parametrize(
    "phase",
    ["manual_mode_idle", "recovery_idle", "starting_up", "stopping"],
)
def test_new_run_phases_are_accepted_and_stored(
    test_client: TestClient, db_session: Session, phase
):
    _register_device(db_session)

    response = test_client.post(
        HEARTBEAT_URL, json={**VALID_HEARTBEAT_BODY, "run_phase": phase}, headers=DEVICE_HEADERS
    )

    assert response.status_code == 200
    assert db_session.scalars(select(Heartbeat)).one().run_phase == phase


def test_legacy_waiting_mode_idle_phase_is_rejected(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(
        HEARTBEAT_URL,
        json={**VALID_HEARTBEAT_BODY, "run_phase": "waiting_mode_idle"},
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 422
    assert db_session.scalars(select(Heartbeat)).first() is None


def test_recovery_idle_crash_details_are_stored_and_superuser_only(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    body = {**CRITICAL_ERROR_BODY, "run_phase": "recovery_idle"}

    response = test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)

    assert response.status_code == 200
    stored = db_session.scalars(select(Heartbeat)).one()
    assert stored.run_phase == "recovery_idle"
    assert stored.critical_error == CRITICAL_ERROR
    regular = test_client.get(
        f"{HEARTBEAT_URL}/{KNOWN_DEVICE_ID}", headers=_regular_user_headers(db_session, test_client)
    ).json()
    assert regular["run_phase"] == "recovery_idle"
    assert regular["critical_error"] is None


def test_recovery_idle_rejects_malformed_crash_details(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    body = {
        **CRITICAL_ERROR_BODY,
        "run_phase": "recovery_idle",
        "critical_error": {**CRITICAL_ERROR, "fingerprint": "x" * 100_000},
    }

    response = test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)

    assert response.status_code == 422


def test_critical_error_is_none_when_omitted(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    test_client.post(HEARTBEAT_URL, json=VALID_HEARTBEAT_BODY, headers=DEVICE_HEADERS)

    assert db_session.scalars(select(Heartbeat)).one().critical_error is None


@pytest.mark.parametrize(
    "critical_error",
    [
        {**CRITICAL_ERROR, "fingerprint": "x" * 100_000},
        {**CRITICAL_ERROR, "action": "x" * 100_000},
        {**CRITICAL_ERROR, "same_error_count": "many"},
        {**CRITICAL_ERROR, "consecutive_reboots": -1},
        {**CRITICAL_ERROR, "unexpected": "field"},
        {"fingerprint": "only-this"},
        "not-an-object",
    ],
)
def test_malformed_or_oversized_critical_error_is_rejected(
    test_client: TestClient, db_session: Session, critical_error
):
    _register_device(db_session)
    body = {**CRITICAL_ERROR_BODY, "critical_error": critical_error}

    response = test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)

    assert response.status_code == 422
    assert db_session.scalars(select(Heartbeat)).all() == []


def test_critical_error_allows_null_fingerprint(test_client: TestClient, db_session: Session):
    _register_device(db_session)
    body = {**CRITICAL_ERROR_BODY, "critical_error": {**CRITICAL_ERROR, "fingerprint": None}}

    response = test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text


def test_critical_error_details_are_visible_to_superuser_on_both_endpoints(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    headers = _superuser_headers(db_session, test_client)
    test_client.post(HEARTBEAT_URL, json=CRITICAL_ERROR_BODY, headers=DEVICE_HEADERS)

    single = test_client.get(f"{HEARTBEAT_URL}/{KNOWN_DEVICE_ID}", headers=headers).json()
    listed = test_client.get(HEARTBEAT_URL, headers=headers).json()["heartbeats"][0]

    assert single["critical_error"] == CRITICAL_ERROR
    assert listed["critical_error"] == CRITICAL_ERROR


def test_critical_error_details_are_hidden_from_regular_user_but_phase_is_visible(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    test_client.post(HEARTBEAT_URL, json=CRITICAL_ERROR_BODY, headers=DEVICE_HEADERS)
    headers = _regular_user_headers(db_session, test_client)

    single = test_client.get(f"{HEARTBEAT_URL}/{KNOWN_DEVICE_ID}", headers=headers).json()
    listed = test_client.get(HEARTBEAT_URL, headers=headers).json()["heartbeats"][0]

    for summary in (single, listed):
        assert summary["run_phase"] == "critical_error"
        assert summary["critical_error"] is None
        assert "gps_reader" not in str(summary)


@pytest.mark.parametrize(
    ("current_config", "expected"),
    [
        ({"system_mode": "manual"}, "manual"),
        ({"system_mode": "waiting"}, None),
        ({"system_mode": "auto", "mode": "manual"}, "auto"),
        ({"mode": "manual"}, "manual"),
        ({"system_mode": "bogus"}, None),
        ({"system_mode": ["auto"]}, None),
        ({"rsrp_threshold": -100.0}, None),
        (None, None),
    ],
)
def test_system_mode_is_derived_from_current_config_for_regular_user(
    test_client: TestClient, db_session: Session, current_config, expected
):
    _register_device(db_session)
    body = {**VALID_HEARTBEAT_BODY}
    if current_config is not None:
        body["current_config"] = current_config
    test_client.post(HEARTBEAT_URL, json=body, headers=DEVICE_HEADERS)
    headers = _regular_user_headers(db_session, test_client)

    single = test_client.get(f"{HEARTBEAT_URL}/{KNOWN_DEVICE_ID}", headers=headers).json()
    listed = test_client.get(HEARTBEAT_URL, headers=headers).json()["heartbeats"][0]

    assert single["system_mode"] == expected
    assert listed["system_mode"] == expected
    assert single["current_config"] is None


def test_system_mode_exposes_no_other_config_to_regular_user(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    test_client.post(HEARTBEAT_URL, json=CRITICAL_ERROR_BODY, headers=DEVICE_HEADERS)
    headers = _regular_user_headers(db_session, test_client)

    summary = test_client.get(f"{HEARTBEAT_URL}/{KNOWN_DEVICE_ID}", headers=headers).json()

    assert "rsrp_threshold" not in str(summary)
