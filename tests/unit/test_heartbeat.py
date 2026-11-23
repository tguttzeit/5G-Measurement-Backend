"""Tests for heartbeat endpoints - basic endpoint tests without database."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_heartbeat_endpoint_missing_device_id():
    """Test heartbeat endpoint fails without device_id."""
    payload = {
        "since_run_start": {"datapoints_total": 100, "good": 80, "bad": 15, "invalid": 5},
        "pipeline_broken": False,
        "storage": {"pending_files": 3, "disk_free_bytes": 50000000000},
    }

    response = client.post(
        "/heartbeat",
        json=payload,
        headers={"X-Device-Key": "some-key"},
    )

    assert response.status_code == 401


def test_heartbeat_endpoint_missing_api_key():
    """Test heartbeat endpoint fails without API key."""
    payload = {
        "since_run_start": {"datapoints_total": 100, "good": 80, "bad": 15, "invalid": 5},
        "pipeline_broken": False,
        "storage": {"pending_files": 3, "disk_free_bytes": 50000000000},
    }

    response = client.post(
        "/heartbeat",
        json=payload,
        headers={"X-Device-ID": "test-device"},
    )

    assert response.status_code == 401
