"""Tests for measurement upload endpoint - basic endpoint tests without database."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID_PAYLOAD = [
    {
        "timestamp": "2026-07-30T12:00:00.000000Z",
        "device_id": "test-device",
        "mission_type": "ground",
        "fix": {
            "position": {"latitude": 52.5, "longitude": 13.4, "altitude": 34.2},
            "num_satellites": 8,
            "placeholder": False,
        },
        "cell_sample": {
            "rat": "LTE",
            "mcc": 262,
            "mnc": 1,
            "cell_id": 12345,
            "pci": 100,
            "tac": 5000,
            "rsrp": -95.0,
            "rsrq": -10.0,
            "rssi": -70.0,
            "sinr": 12.0,
            "band": 3,
            "channel": 1500,
            "vendor_specific_extras": None,
        },
    }
]


def test_measurements_endpoint_missing_device_id():
    """Test measurements endpoint fails without X-Device-ID header."""
    response = client.post(
        "/measurements",
        json=VALID_PAYLOAD,
        headers={"X-Device-Key": "some-key"},
    )

    assert response.status_code == 401


def test_measurements_endpoint_missing_api_key():
    """Test measurements endpoint fails without X-Device-Key header."""
    response = client.post(
        "/measurements",
        json=VALID_PAYLOAD,
        headers={"X-Device-ID": "test-device"},
    )

    assert response.status_code == 401


def test_measurements_endpoint_checks_auth_before_parsing_body():
    """Auth must be checked before the body is parsed/validated, even for a malformed body.

    Device auth is a FastAPI dependency (not called manually inside the endpoint) so that an
    unauthenticated request is rejected before the - potentially large - body is ever parsed.
    A malformed body with no auth headers should still fail with 401, not 422.
    """
    response = client.post(
        "/measurements",
        json=[{"not": "a valid datapoint"}],
    )

    assert response.status_code == 401


# --- public points endpoint ---------------------------------------


def test_points_requires_metric():
    response = TestClient(app).get("/measurements/points", params={"bbox": "13.0,52.0,13.5,52.5"})

    assert response.status_code == 422


def test_points_rejects_malformed_bbox_without_needing_auth():
    response = TestClient(app).get(
        "/measurements/points", params={"bbox": "not,a,bbox", "metric": "rsrp"}
    )

    assert response.status_code == 400


def test_public_point_schemas_structurally_exclude_identifying_fields():
    from app.schemas.latency_map import LatencyPublicPointProperties
    from app.schemas.measurement import PublicPointProperties

    identifying = {
        "device_id",
        "timestamp",
        "start_timestamp",
        "end_timestamp",
        "run_id",
        "raw_data",
    }
    assert identifying.isdisjoint(PublicPointProperties.model_fields)
    assert identifying.isdisjoint(LatencyPublicPointProperties.model_fields)
