"""Unit tests for the `/measurements/extent` query-param validation.

No real DB needed here: bad input is rejected before any query touches the database, same
pattern as test_measurements_heatmap.py.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_extent_requires_metric():
    response = client.get("/measurements/extent")

    assert response.status_code == 422


def test_extent_rejects_invalid_metric():
    response = client.get("/measurements/extent", params={"metric": "not-a-metric"})

    assert response.status_code == 422


def test_extent_rejects_non_integer_campaign_id():
    response = client.get(
        "/measurements/extent", params={"metric": "rsrp", "campaign_id": "not-an-id"}
    )

    assert response.status_code == 422
