"""Basic auth-boundary tests for the gps-fix-test endpoints, without a database - same style as
test_heartbeat.py. Full round-trip coverage (registered device, staleness, superuser auth) lives
in tests/integration/test_api/test_gps_fix_test.py, since it needs a real device row.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

STATUS_URL = "/devices/some-device/gps-fix-test/status"


def test_post_status_missing_device_id_header_is_rejected():
    response = client.post(
        STATUS_URL,
        json={"num_satellites": 7, "has_fix": True, "elapsed_s": 10},
        headers={"X-Device-Key": "some-key"},
    )

    assert response.status_code == 401


def test_post_status_missing_device_key_header_is_rejected():
    response = client.post(
        STATUS_URL,
        json={"num_satellites": 7, "has_fix": True, "elapsed_s": 10},
        headers={"X-Device-ID": "some-device"},
    )

    assert response.status_code == 401


def test_get_status_without_auth_is_rejected():
    response = client.get(STATUS_URL)

    assert response.status_code == 401
