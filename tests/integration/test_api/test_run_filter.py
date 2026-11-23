"""Integration tests for the `run_id` filter on the authenticated map endpoints, and for `run_id`
never surfacing through the public ones: a public caller could otherwise correlate
points back to a single drive.
"""
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from tests.integration.test_api.test_latency_map import _add as _add_latency
from tests.integration.test_api.test_latency_map import _result
from tests.integration.test_api.test_measurements_detailed import (
    BERLIN_BBOX,
    _auth_headers,
    _campaign,
    _measurement,
)

DETAILED_URL = "/measurements/detailed"
LATENCY_RAW_URL = "/latency-results/raw"
SECRET_RUN_ID = "run-that-must-stay-private"


def _measurement_in_run(run_id: str, lat: float = 52.1, **kwargs) -> Measurement:
    return _measurement(lat, 13.1, run_id=run_id, **kwargs)


def _latency_in_run(run_id: str, **kwargs) -> LatencyTestResult:
    return _result(run_id=run_id, **kwargs)


def _detailed(test_client: TestClient, headers: dict, view: str, **params):
    return test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": view, **params},
        headers=headers,
    )


# --- Authenticated filters ---------------------------------------------------


def test_detailed_raw_view_filters_by_run_id(test_client: TestClient, db_session: Session):
    db_session.add_all(
        [
            _measurement_in_run("run-a", lat=52.1),
            _measurement_in_run("run-a", lat=52.2),
            _measurement_in_run("run-b", lat=52.3),
        ]
    )
    db_session.commit()
    headers = _auth_headers(db_session, test_client)

    response = _detailed(test_client, headers, "raw", run_id="run-a")

    assert response.status_code == 200, response.text
    latitudes = {f["geometry"]["coordinates"][1] for f in response.json()["features"]}
    assert latitudes == {52.1, 52.2}


def test_detailed_aggregate_view_filters_by_run_id(test_client: TestClient, db_session: Session):
    db_session.add_all([_measurement_in_run("run-a"), _measurement_in_run("run-b")])
    db_session.commit()
    headers = _auth_headers(db_session, test_client)

    response = _detailed(test_client, headers, "aggregate", run_id="run-a")

    assert [f["properties"]["count"] for f in response.json()["features"]] == [1]


def test_detailed_run_id_combines_with_device_id_to_pick_one_devices_run(
    test_client: TestClient, db_session: Session
):
    db_session.add_all(
        [
            _measurement_in_run("shared", lat=52.1, device_id="device-1"),
            _measurement_in_run("shared", lat=52.2, device_id="device-2"),
        ]
    )
    db_session.commit()
    headers = _auth_headers(db_session, test_client)

    response = _detailed(test_client, headers, "raw", run_id="shared", device_id="device-2")

    latitudes = [f["geometry"]["coordinates"][1] for f in response.json()["features"]]
    assert latitudes == [52.2]


def test_detailed_run_id_filter_rejects_overlong_values(
    test_client: TestClient, db_session: Session
):
    headers = _auth_headers(db_session, test_client)

    response = _detailed(test_client, headers, "raw", run_id="x" * 601)

    assert response.status_code == 422


def test_latency_raw_filters_by_run_id(test_client: TestClient, db_session: Session):
    _add_latency(
        db_session,
        _latency_in_run("run-a", idempotency_key="a1"),
        _latency_in_run("run-a", idempotency_key="a2"),
        _latency_in_run("run-b", idempotency_key="b1"),
    )
    headers = _auth_headers(db_session, test_client)

    response = test_client.get(
        LATENCY_RAW_URL,
        params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms", "run_id": "run-a"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["features"]) == 2


# --- Public endpoints never expose or accept run_id ---------------------------


def _seed_public_data(db_session: Session) -> None:
    _campaign(db_session, "August", date(2026, 8, 1), date(2026, 8, 31))
    db_session.add_all(
        [
            _measurement_in_run(SECRET_RUN_ID, timestamp=datetime(2026, 8, 1, tzinfo=UTC)),
            _measurement_in_run("other-run", lat=52.3, timestamp=datetime(2026, 8, 1, tzinfo=UTC)),
        ]
    )
    db_session.commit()
    _add_latency(db_session, _latency_in_run(SECRET_RUN_ID))


def test_public_endpoints_never_return_run_ids(test_client: TestClient, db_session: Session):
    _seed_public_data(db_session)
    measurement_params = {"bbox": BERLIN_BBOX, "metric": "rsrp"}
    latency_params = {"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"}

    responses = [
        test_client.get("/measurements/heatmap", params=measurement_params),
        test_client.get("/measurements/extent", params={"metric": "rsrp"}),
        test_client.get("/measurements/campaigns"),
        test_client.get("/measurements/export", params={**measurement_params, "format": "csv"}),
        test_client.get("/measurements/export", params={**measurement_params, "format": "geojson"}),
        test_client.get("/latency-results/heatmap", params=latency_params),
        test_client.get("/latency-results/extent", params={"metric": "baseline_rtt_ms"}),
    ]

    for response in responses:
        assert response.status_code == 200, response.request.url
        assert SECRET_RUN_ID not in response.text, response.request.url
        assert "run_id" not in response.text, response.request.url


def test_public_endpoints_ignore_a_run_id_filter(test_client: TestClient, db_session: Session):
    _seed_public_data(db_session)
    measurement_params = {"bbox": BERLIN_BBOX, "metric": "rsrp"}

    without_filter = test_client.get("/measurements/heatmap", params=measurement_params)
    with_filter = test_client.get(
        "/measurements/heatmap", params={**measurement_params, "run_id": "other-run"}
    )
    latency_without = test_client.get(
        "/latency-results/heatmap", params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"}
    )
    latency_with = test_client.get(
        "/latency-results/heatmap",
        params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms", "run_id": "other-run"},
    )

    assert with_filter.json() == without_filter.json()
    assert latency_with.json() == latency_without.json()
    assert len(with_filter.json()["features"]) > 0
    assert len(latency_with.json()["features"]) > 0
