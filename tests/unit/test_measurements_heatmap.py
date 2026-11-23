"""Unit tests for the heatmap/export query-param validation.

No real DB needed here: bad input is rejected before any query touches the database, same
pattern as test_measurements.py's auth-before-body-parse tests.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_heatmap_requires_bbox():
    response = client.get("/measurements/heatmap", params={"metric": "rsrp"})

    assert response.status_code == 422


def test_heatmap_requires_metric():
    response = client.get(
        "/measurements/heatmap", params={"bbox": "13.0,52.0,13.5,52.5"}
    )

    assert response.status_code == 422


def test_heatmap_rejects_malformed_bbox():
    response = client.get(
        "/measurements/heatmap",
        params={"bbox": "not,a,bbox", "metric": "rsrp"},
    )

    assert response.status_code == 400


def test_heatmap_rejects_bbox_with_wrong_number_of_values():
    response = client.get(
        "/measurements/heatmap",
        params={"bbox": "13.0,52.0,13.5", "metric": "rsrp"},
    )

    assert response.status_code == 400


def test_heatmap_rejects_out_of_range_longitude():
    response = client.get(
        "/measurements/heatmap",
        params={"bbox": "-200.0,52.0,13.5,52.5", "metric": "rsrp"},
    )

    assert response.status_code == 400


def test_heatmap_rejects_out_of_range_latitude():
    response = client.get(
        "/measurements/heatmap",
        params={"bbox": "13.0,-100.0,13.5,52.5", "metric": "rsrp"},
    )

    assert response.status_code == 400


def test_heatmap_rejects_inverted_bbox():
    response = client.get(
        "/measurements/heatmap",
        params={"bbox": "13.5,52.5,13.0,52.0", "metric": "rsrp"},
    )

    assert response.status_code == 400


def test_heatmap_rejects_invalid_metric():
    response = client.get(
        "/measurements/heatmap",
        params={"bbox": "13.0,52.0,13.5,52.5", "metric": "not-a-metric"},
    )

    assert response.status_code == 422


def test_heatmap_rejects_non_integer_campaign_id():
    response = client.get(
        "/measurements/heatmap",
        params={"bbox": "13.0,52.0,13.5,52.5", "metric": "rsrp", "campaign_id": "not-an-id"},
    )

    assert response.status_code == 422


def test_export_requires_format():
    response = client.get(
        "/measurements/export",
        params={"bbox": "13.0,52.0,13.5,52.5", "metric": "rsrp"},
    )

    assert response.status_code == 422


def test_export_rejects_invalid_format():
    response = client.get(
        "/measurements/export",
        params={"bbox": "13.0,52.0,13.5,52.5", "metric": "rsrp", "format": "png"},
    )

    assert response.status_code == 422
