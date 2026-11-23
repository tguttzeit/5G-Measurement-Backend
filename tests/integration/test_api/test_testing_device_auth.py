"""Tests for device-key auth for POST /api/testing/results.

Context: app/routers/testing.py used to gate every route (including POST /testing/results) behind
`current_superuser` -- a human's JWT. A a *second* auth path, device-key based, but ONLY for
POST /testing/results were added previously (the endpoint an unattended device script actually
calls); the dashboard-facing GET/DELETE/summary routes must keep requiring a superuser JWT and
must reject device-key auth outright.

# The original resolution for the open question forced is_testing to True server-side for any
device-authenticated submission. That was later reverserd: the one physical device is
shared between testing and production use, so a device-key submission honors is_testing exactly
like a superuser-JWT submission does -- there is no way for the shared device to ever record a
real production row otherwise.

The GET/DELETE/summary rejection tests below assert *today's* real behavior (gated behind
current_superuser, which 401s on missing/wrong auth without touching the DB) and must keep passing
now that POST /testing/results has grown a second auth path, since the device auth path
must not open them up.

Needs a real Postgres (test_results.device_id is a real FK into devices.device_id), so this lives
under tests/integration rather than tests/unit -- the test_client/db_session
fixtures used here are in tests/integration/conftest.py.
"""
import hashlib
import secrets

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from app.models import Device, TestResult
from app.models.user import User

KNOWN_DEVICE_ID = "testing-auth-device-01"
KNOWN_DEVICE_KEY = "correct-horse-battery-staple"
DEVICE_HEADERS = {"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": KNOWN_DEVICE_KEY}

VALID_RESULT_PAYLOAD = {
    "device_id": KNOWN_DEVICE_ID,
    "test_type": "modem",
    "status": "passed",
}


def _register_known_device(db_session: Session) -> None:
    db_session.add(
        Device(
            device_id=KNOWN_DEVICE_ID,
            api_key_hash=hashlib.sha256(KNOWN_DEVICE_KEY.encode()).hexdigest(),
            hmac_secret=secrets.token_hex(32),
        )
    )
    db_session.commit()


def test_post_results_accepts_device_key_auth(test_client, db_session):
    _register_known_device(db_session)

    response = test_client.post(
        "/testing/results", json=VALID_RESULT_PAYLOAD, headers=DEVICE_HEADERS
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    "method,url",
    [
        ("get", "/testing/results"),
        ("get", "/testing/results/1"),
        ("get", "/testing/summary"),
        ("delete", "/testing/results/1"),
    ],
)
def test_dashboard_routes_reject_device_key_auth_and_still_require_superuser_jwt(
    test_client, method, url
):
    """The critical regression test: POST /testing/results growing a second auth path must not
    leak device-key auth onto the routes that are supposed to stay superuser-JWT-only.
    """
    response = getattr(test_client, method)(url, headers=DEVICE_HEADERS)

    assert response.status_code == 401


def test_payload_device_id_mismatch_returns_403(test_client, db_session):
    _register_known_device(db_session)
    payload = {**VALID_RESULT_PAYLOAD, "device_id": "some-other-device"}

    response = test_client.post("/testing/results", json=payload, headers=DEVICE_HEADERS)

    assert response.status_code == 403


def test_is_testing_honors_payload_under_device_key_auth_even_when_false(test_client, db_session):
    """is_testing is NOT forced server-side. The single physical device is shared
    between testing and production use, so a device-key submission must be able to record a real
    production row (is_testing=False) exactly like a superuser-JWT submission can.
    """
    _register_known_device(db_session)
    payload = {**VALID_RESULT_PAYLOAD, "is_testing": False}

    response = test_client.post("/testing/results", json=payload, headers=DEVICE_HEADERS)

    assert response.status_code == 201
    # Read back via the stored record rather than trusting an echoed request field.
    stored = (
        db_session.query(TestResult)
        .filter_by(device_id=KNOWN_DEVICE_ID)
        .order_by(TestResult.created_at.desc())
        .first()
    )
    assert stored is not None
    assert stored.is_testing is False


@pytest.mark.parametrize(
    "url",
    ["/testing/results", "/testing/results/1", "/testing/summary"],
)
def test_dashboard_read_routes_reject_non_superuser_jwt(test_client, db_session, url):
    """The frontend hides the test visualization from non-superusers; this is the server-side
    enforcement that hiding relies on."""
    db_session.add(
        User(
            email="regular-user",
            hashed_password=PasswordHelper().hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
    )
    db_session.commit()
    login = test_client.post(
        "/auth/login",
        data={"username": "regular-user", "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200, login.text

    response = test_client.get(
        url, headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )

    assert response.status_code == 403
