"""Unit tests for the latency-result map endpoints' query-param validation and auth gate.
No real DB needed: bad input and missing auth are rejected before any query runs.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.latency_map import LatencyMetric

client = TestClient(app)

BBOX = "13.0,52.0,13.5,52.5"


def test_latency_metric_allow_list_is_exactly_the_five_numeric_columns():
    assert {m.value for m in LatencyMetric} == {
        "baseline_rtt_ms",
        "rtt_under_load_ms",
        "rtt_p99_ms",
        "download_mbits_s",
        "upload_mbits_s",
    }


@pytest.mark.parametrize("path", ["heatmap", "extent"])
def test_public_endpoints_require_metric(path):
    response = client.get(f"/latency-results/{path}", params={"bbox": BBOX})

    assert response.status_code == 422


@pytest.mark.parametrize("path", ["heatmap", "extent"])
@pytest.mark.parametrize("metric", ["not-a-metric", "idempotency_key", "rsrp"])
def test_public_endpoints_reject_metric_outside_allow_list(path, metric):
    response = client.get(f"/latency-results/{path}", params={"bbox": BBOX, "metric": metric})

    assert response.status_code == 422


def test_heatmap_requires_bbox():
    response = client.get("/latency-results/heatmap", params={"metric": "baseline_rtt_ms"})

    assert response.status_code == 422


def test_heatmap_rejects_malformed_bbox():
    response = client.get(
        "/latency-results/heatmap", params={"bbox": "not,a,bbox", "metric": "baseline_rtt_ms"}
    )

    assert response.status_code == 400


def test_extent_rejects_non_integer_campaign_id():
    response = client.get(
        "/latency-results/extent",
        params={"metric": "baseline_rtt_ms", "campaign_id": "not-an-id"},
    )

    assert response.status_code == 422


def test_raw_requires_auth():
    response = client.get(
        "/latency-results/raw", params={"bbox": BBOX, "metric": "baseline_rtt_ms"}
    )

    assert response.status_code == 401


def test_post_ingestion_route_is_unaffected_by_the_map_routes():
    response = client.post("/latency-results", json={})

    assert response.status_code in (401, 403, 422)


def test_points_requires_metric_in_allow_list():
    response = client.get("/latency-results/points", params={"bbox": BBOX, "metric": "rsrp"})

    assert response.status_code == 422


def test_points_rejects_malformed_bbox_without_needing_auth():
    response = client.get(
        "/latency-results/points", params={"bbox": "not,a,bbox", "metric": "baseline_rtt_ms"}
    )

    assert response.status_code == 400
