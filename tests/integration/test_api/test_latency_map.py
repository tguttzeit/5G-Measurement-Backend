"""Integration tests for the latency-result map endpoints: public heatmap/extent
and the authenticated raw view.

Needs a real Postgres - the queries extract coordinates from JSONB and group in SQL. See
tests/integration/conftest.py for the fixtures and test_measurements_detailed.py for the
auth-header pattern reused here.
"""

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.app_settings import set_authenticated_raw_row_cap
from app.models.campaign import Campaign
from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from tests.integration.campaign_helpers import date_window_campaign
from tests.integration.run_helpers import run_row
from tests.integration.test_api.test_measurements_detailed import _auth_headers

HEATMAP_URL = "/latency-results/heatmap"
EXTENT_URL = "/latency-results/extent"
RAW_URL = "/latency-results/raw"
BERLIN_BBOX = "13.0,52.0,13.5,52.5"
SUMMER_START = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


def _fix(lat: float, lon: float, placeholder: bool = False) -> dict:
    return {
        "position": {"latitude": lat, "longitude": lon, "altitude": None},
        "num_satellites": 9,
        "placeholder": placeholder,
    }


def _result(
    start: tuple[float, float] = (52.10, 13.10),
    end: tuple[float, float] = (52.12, 13.14),
    device_id: str = "device-1",
    test_type: str = "baseline",
    mission_type: str = "ground",
    run_id: str | None = None,
    start_timestamp: datetime = SUMMER_START,
    placeholder: bool = False,
    idempotency_key: str | None = "secret-key",
    baseline_rtt_ms: float | None = 40.0,
    rtt_under_load_ms: float | None = None,
    rtt_p99_ms: float | None = None,
    download_mbits_s: float | None = None,
    upload_mbits_s: float | None = None,
) -> LatencyTestResult:
    return run_row(
        LatencyTestResult,
        device_id=device_id,
        test_type=test_type,
        flent_test="rrul",
        mission_type=mission_type,
        run_id=run_id,
        start_timestamp=start_timestamp,
        end_timestamp=start_timestamp,
        start_fix=_fix(*start, placeholder=placeholder),
        end_fix=_fix(*end),
        baseline_rtt_ms=baseline_rtt_ms,
        rtt_under_load_ms=rtt_under_load_ms,
        rtt_p99_ms=rtt_p99_ms,
        download_mbits_s=download_mbits_s,
        upload_mbits_s=upload_mbits_s,
        idempotency_key=idempotency_key,
    )


def _add(db_session: Session, *rows: LatencyTestResult) -> None:
    from app.models import Device

    for device_id in {r.device_id for r in rows}:
        if db_session.get(Device, device_id) is None:
            db_session.add(Device(device_id=device_id, api_key_hash="x", hmac_secret="x"))
    db_session.flush()
    db_session.add_all(rows)
    db_session.commit()


def _add_with_run_measurements(db_session: Session, *rows: LatencyTestResult) -> None:
    """Like `_add`, plus one measurement per run: runs come into existence through measurement
    uploads, and the default campaign is the one whose runs have the newest measurements."""
    _add(db_session, *rows)
    first_start: dict[int, LatencyTestResult] = {}
    for row in rows:
        first_start.setdefault(row.run_pk, row)
    db_session.add_all(
        Measurement(
            timestamp=row.start_timestamp,
            device_id=row.device_id,
            run_pk=row.run_pk,
            latitude=52.1,
            longitude=13.1,
            placeholder=False,
            rsrp=-90.0,
            raw_data={},
        )
        for row in first_start.values()
    )
    db_session.commit()


def _campaign(db_session: Session, name: str, start_date: date, end_date: date) -> Campaign:
    return date_window_campaign(db_session, name, start_date, end_date)


def _summer_campaign(db_session: Session) -> Campaign:
    return _campaign(db_session, "summer-2026", date(2026, 7, 1), date(2026, 8, 31))


# --- heatmap -------------------------------------------------------------------


def test_heatmap_is_public_and_positions_rows_at_start_end_midpoint(test_client, db_session):
    campaign = _summer_campaign(db_session)
    _add(db_session, _result(start=(52.10, 13.10), end=(52.14, 13.18), baseline_rtt_ms=40.0))

    response = test_client.get(
        HEATMAP_URL,
        params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms", "campaign_id": campaign.id},
    )

    assert response.status_code == 200
    features = response.json()["features"]
    assert len(features) == 1
    lon, lat = features[0]["geometry"]["coordinates"]
    # The cell center sits within one grid cell of the midpoint (13.14, 52.12), and the start
    # and end are far enough apart that a start-only position would land in a different spot.
    assert abs(lon - 13.14) < 0.05
    assert abs(lat - 52.12) < 0.05
    assert features[0]["properties"] == {"value": 40.0, "count": 1}


def test_heatmap_averages_rows_sharing_a_cell(test_client, db_session):
    campaign = _summer_campaign(db_session)
    _add(
        db_session,
        _result(baseline_rtt_ms=40.0, idempotency_key="a"),
        _result(baseline_rtt_ms=60.0, idempotency_key="b"),
    )

    response = test_client.get(
        HEATMAP_URL,
        params={"bbox": "13.0,52.0,13.5,52.5", "metric": "baseline_rtt_ms",
                "campaign_id": campaign.id},
    )

    features = response.json()["features"]
    assert len(features) == 1
    assert features[0]["properties"] == {"value": 50.0, "count": 2}


def test_heatmap_only_includes_rows_where_selected_metric_is_non_null(test_client, db_session):
    campaign = _summer_campaign(db_session)
    _add(
        db_session,
        _result(baseline_rtt_ms=40.0, idempotency_key="baseline"),
        _result(
            test_type="under_load",
            baseline_rtt_ms=None,
            rtt_under_load_ms=120.0,
            download_mbits_s=80.0,
            idempotency_key="under-load",
        ),
    )

    def values(metric: str) -> list[float]:
        response = test_client.get(
            HEATMAP_URL,
            params={"bbox": BERLIN_BBOX, "metric": metric, "campaign_id": campaign.id},
        )
        return [f["properties"]["value"] for f in response.json()["features"]]

    assert values("baseline_rtt_ms") == [40.0]
    assert values("rtt_under_load_ms") == [120.0]
    assert values("download_mbits_s") == [80.0]
    assert values("upload_mbits_s") == []


def test_heatmap_excludes_placeholder_fixes(test_client, db_session):
    campaign = _summer_campaign(db_session)
    _add(db_session, _result(placeholder=True))

    response = test_client.get(
        HEATMAP_URL,
        params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms", "campaign_id": campaign.id},
    )

    assert response.json()["features"] == []


def test_heatmap_excludes_rows_outside_bbox(test_client, db_session):
    campaign = _summer_campaign(db_session)
    _add(db_session, _result(start=(48.1, 11.5), end=(48.2, 11.6)))

    response = test_client.get(
        HEATMAP_URL,
        params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms", "campaign_id": campaign.id},
    )

    assert response.json()["features"] == []


def test_heatmap_scopes_to_explicit_campaign(test_client, db_session):
    summer = _summer_campaign(db_session)
    _campaign(db_session, "winter-2026", date(2026, 12, 1), date(2027, 2, 28))
    _add(
        db_session,
        _result(baseline_rtt_ms=40.0, idempotency_key="summer"),
        _result(
            baseline_rtt_ms=90.0,
            start_timestamp=datetime(2026, 12, 15, tzinfo=UTC),
            idempotency_key="winter",
        ),
    )

    response = test_client.get(
        HEATMAP_URL,
        params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms", "campaign_id": summer.id},
    )

    features = response.json()["features"]
    assert [f["properties"]["value"] for f in features] == [40.0]


def test_heatmap_defaults_to_most_recent_campaign_and_never_blends(test_client, db_session):
    _campaign(db_session, "old", date(2020, 1, 1), date(2020, 1, 31))
    _campaign(db_session, "newer", date(2021, 1, 1), date(2021, 1, 31))
    _add_with_run_measurements(
        db_session,
        _result(
            baseline_rtt_ms=30.0,
            start_timestamp=datetime(2020, 1, 10, tzinfo=UTC),
            idempotency_key="old",
        ),
        _result(
            baseline_rtt_ms=70.0,
            start_timestamp=datetime(2021, 1, 10, tzinfo=UTC),
            idempotency_key="newer",
        ),
    )

    response = test_client.get(
        HEATMAP_URL, params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"}
    )

    assert [f["properties"]["value"] for f in response.json()["features"]] == [70.0]


def test_heatmap_with_no_campaigns_returns_nothing(test_client, db_session):
    _add(db_session, _result())

    response = test_client.get(
        HEATMAP_URL, params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"}
    )

    assert response.status_code == 200
    assert response.json()["features"] == []


def test_heatmap_unknown_campaign_is_404(test_client):
    response = test_client.get(
        HEATMAP_URL,
        params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms", "campaign_id": 999},
    )

    assert response.status_code == 404


def test_heatmap_filters_by_device_and_mission_type(test_client, db_session):
    campaign = _summer_campaign(db_session)
    _add(
        db_session,
        _result(device_id="device-1", mission_type="ground", baseline_rtt_ms=40.0,
                idempotency_key="a"),
        _result(device_id="device-2", mission_type="drone", baseline_rtt_ms=80.0,
                idempotency_key="b"),
    )

    def values(**extra) -> list[float]:
        response = test_client.get(
            HEATMAP_URL,
            params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms",
                    "campaign_id": campaign.id, **extra},
        )
        return [f["properties"]["value"] for f in response.json()["features"]]

    assert values(device_id="device-2") == [80.0]
    assert values(mission_type="ground") == [40.0]


def test_heatmap_response_never_leaks_device_id_timestamps_or_idempotency_key(
    test_client, db_session
):
    campaign = _summer_campaign(db_session)
    _add(db_session, _result(device_id="device-secret", idempotency_key="secret-key"))

    response = test_client.get(
        HEATMAP_URL,
        params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms", "campaign_id": campaign.id},
    )

    assert "device-secret" not in response.text
    assert "secret-key" not in response.text
    assert "timestamp" not in response.text


# --- extent --------------------------------------------------------------------


def test_extent_covers_both_ends_of_every_matching_row(test_client, db_session):
    campaign = _summer_campaign(db_session)
    _add(
        db_session,
        _result(start=(52.10, 13.30), end=(52.05, 13.10), idempotency_key="a"),
        _result(start=(52.20, 13.20), end=(52.40, 13.25), idempotency_key="b"),
    )

    response = test_client.get(
        EXTENT_URL, params={"metric": "baseline_rtt_ms", "campaign_id": campaign.id}
    )

    assert response.status_code == 200
    assert response.json()["bbox"] == [13.10, 52.05, 13.30, 52.40]


def test_extent_is_null_when_nothing_matches(test_client, db_session):
    campaign = _summer_campaign(db_session)
    _add(db_session, _result())

    response = test_client.get(
        EXTENT_URL, params={"metric": "upload_mbits_s", "campaign_id": campaign.id}
    )

    assert response.json() == {"bbox": None}


def test_extent_with_no_campaigns_is_null(test_client):
    response = test_client.get(EXTENT_URL, params={"metric": "baseline_rtt_ms"})

    assert response.status_code == 200
    assert response.json() == {"bbox": None}


# --- raw -----------------------------------------------------------------------


def test_raw_requires_auth(test_client):
    response = test_client.get(RAW_URL, params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"})

    assert response.status_code == 401


def test_raw_returns_line_with_both_ends_and_all_five_metrics(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    _add(
        db_session,
        _result(
            start=(52.10, 13.10),
            end=(52.12, 13.14),
            test_type="under_load",
            baseline_rtt_ms=40.0,
            rtt_under_load_ms=120.0,
            rtt_p99_ms=300.0,
            download_mbits_s=80.0,
            upload_mbits_s=20.0,
        ),
    )

    response = test_client.get(
        RAW_URL, params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"}, headers=headers
    )

    assert response.status_code == 200
    feature = response.json()["features"][0]
    assert feature["geometry"] == {
        "type": "LineString",
        "coordinates": [[13.10, 52.10], [13.14, 52.12]],
    }
    properties = feature["properties"]
    assert properties["device_id"] == "device-1"
    assert properties["test_type"] == "under_load"
    assert properties["start_timestamp"].startswith("2026-08-01T10:00:00")
    assert (
        properties["baseline_rtt_ms"],
        properties["rtt_under_load_ms"],
        properties["rtt_p99_ms"],
        properties["download_mbits_s"],
        properties["upload_mbits_s"],
    ) == (40.0, 120.0, 300.0, 80.0, 20.0)


def test_raw_gates_rows_on_selected_metric_and_never_returns_idempotency_key(
    test_client, db_session
):
    headers = _auth_headers(db_session, test_client)
    _add(db_session, _result(baseline_rtt_ms=None, download_mbits_s=80.0))

    def get(metric: str):
        return test_client.get(
            RAW_URL, params={"bbox": BERLIN_BBOX, "metric": metric}, headers=headers
        )

    assert get("baseline_rtt_ms").json()["features"] == []
    included = get("download_mbits_s")
    assert len(included.json()["features"]) == 1
    assert "secret-key" not in included.text


def test_raw_defaults_to_all_time_unlike_public_endpoints(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    _campaign(db_session, "unrelated", date(2020, 1, 1), date(2020, 1, 31))
    _add(db_session, _result())

    response = test_client.get(
        RAW_URL, params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"}, headers=headers
    )

    assert len(response.json()["features"]) == 1


def test_raw_scopes_to_explicit_campaign(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    summer = _summer_campaign(db_session)
    _add(
        db_session,
        _result(idempotency_key="summer"),
        _result(start_timestamp=datetime(2026, 12, 15, tzinfo=UTC), idempotency_key="winter"),
    )

    response = test_client.get(
        RAW_URL,
        params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms", "campaign_id": summer.id},
        headers=headers,
    )

    assert len(response.json()["features"]) == 1


def test_raw_is_unlimited_by_default_for_logged_in_users(test_client, db_session, monkeypatch):
    headers = _auth_headers(db_session, test_client)
    _add(db_session, *[_result(idempotency_key=f"k{i}") for i in range(3)])
    monkeypatch.setattr("app.latency_results_query.RAW_ROW_CAP", 2)

    response = test_client.get(
        RAW_URL, params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"}, headers=headers
    )

    assert response.status_code == 200
    assert len(response.json()["features"]) == 3


def test_raw_400_when_configured_row_cap_exceeded(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    _add(db_session, *[_result(idempotency_key=f"k{i}") for i in range(3)])
    set_authenticated_raw_row_cap(db_session, 2, updated_by=None)

    response = test_client.get(
        RAW_URL, params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"}, headers=headers
    )

    assert response.status_code == 400


def test_raw_under_the_configured_row_cap_succeeds(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    _add(db_session, *[_result(idempotency_key=f"k{i}") for i in range(3)])
    set_authenticated_raw_row_cap(db_session, 3, updated_by=None)

    response = test_client.get(
        RAW_URL, params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"}, headers=headers
    )

    assert response.status_code == 200
    assert len(response.json()["features"]) == 3


# --- points (public) -------------------------------------------------

POINTS_URL = "/latency-results/points"
LATENCY_FORBIDDEN_KEYS = {
    "device_id",
    "start_timestamp",
    "end_timestamp",
    "timestamp",
    "run_id",
    "idempotency_key",
    "test_type",
}


def _points(test_client, **params):
    return test_client.get(
        POINTS_URL, params={"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms", **params}
    )


def test_points_is_public_and_returns_line_with_all_five_metrics(test_client, db_session):
    _campaign(db_session, "All", date(2026, 1, 1), date(2026, 12, 31))
    _add_with_run_measurements(db_session, _result(rtt_p99_ms=90.0, download_mbits_s=55.5))

    response = _points(test_client)

    assert response.status_code == 200
    [feature] = response.json()["features"]
    assert feature["geometry"] == {
        "type": "LineString",
        "coordinates": [[13.10, 52.10], [13.14, 52.12]],
    }
    assert feature["properties"] == {
        "baseline_rtt_ms": 40.0,
        "rtt_under_load_ms": None,
        "rtt_p99_ms": 90.0,
        "download_mbits_s": 55.5,
        "upload_mbits_s": None,
    }


def test_points_never_contains_identifying_keys(test_client, db_session):
    _campaign(db_session, "All", date(2026, 1, 1), date(2026, 12, 31))
    _add_with_run_measurements(
        db_session, _result(device_id="secret-device", idempotency_key="secret-key")
    )

    response = _points(test_client)

    assert "secret-device" not in response.text
    assert "secret-key" not in response.text
    [feature] = response.json()["features"]
    assert LATENCY_FORBIDDEN_KEYS.isdisjoint(feature["properties"])
    assert LATENCY_FORBIDDEN_KEYS.isdisjoint(feature)


def test_points_ignores_device_id_param(test_client, db_session):
    _campaign(db_session, "All", date(2026, 1, 1), date(2026, 12, 31))
    _add_with_run_measurements(
        db_session,
        _result(device_id="device-a", idempotency_key="a"),
        _result(device_id="device-b", idempotency_key="b"),
    )

    response = _points(test_client, device_id="device-a")

    assert len(response.json()["features"]) == 2


def test_points_excludes_placeholder_rows_and_rows_missing_the_metric(test_client, db_session):
    _campaign(db_session, "All", date(2026, 1, 1), date(2026, 12, 31))
    _add_with_run_measurements(
        db_session,
        _result(idempotency_key="ok"),
        _result(placeholder=True, idempotency_key="placeholder"),
        _result(baseline_rtt_ms=None, download_mbits_s=10.0, idempotency_key="other-metric"),
    )

    response = _points(test_client)

    assert len(response.json()["features"]) == 1


def test_points_defaults_to_most_recent_campaign_and_never_blends(test_client, db_session):
    _campaign(db_session, "Old", date(2026, 1, 1), date(2026, 1, 31))
    newer = _campaign(db_session, "Newer", date(2026, 2, 1), date(2026, 2, 28))
    _add_with_run_measurements(
        db_session,
        _result(start_timestamp=datetime(2026, 1, 15, tzinfo=UTC), idempotency_key="old"),
        _result(start_timestamp=datetime(2026, 2, 15, tzinfo=UTC), idempotency_key="new"),
    )

    default = _points(test_client)
    explicit = _points(test_client, campaign_id=newer.id)

    assert default.json() == explicit.json()
    assert len(default.json()["features"]) == 1


def test_points_with_no_campaigns_returns_nothing(test_client, db_session):
    _add(db_session, _result())

    response = _points(test_client)

    assert response.status_code == 200
    assert response.json()["features"] == []


def test_points_unknown_campaign_is_404(test_client):
    assert _points(test_client, campaign_id=99999).status_code == 404


def test_points_400_when_row_cap_exceeded(test_client, db_session, monkeypatch):
    _campaign(db_session, "All", date(2026, 1, 1), date(2026, 12, 31))
    _add_with_run_measurements(db_session, *[_result(idempotency_key=f"k{i}") for i in range(3)])
    monkeypatch.setattr("app.latency_results_query.RAW_ROW_CAP", 2)

    response = _points(test_client)

    assert response.status_code == 400


def test_points_stay_capped_when_the_authenticated_cap_is_unlimited(
    test_client, db_session, monkeypatch
):
    _campaign(db_session, "All", date(2026, 1, 1), date(2026, 12, 31))
    _add_with_run_measurements(db_session, *[_result(idempotency_key=f"k{i}") for i in range(3)])
    monkeypatch.setattr("app.latency_results_query.RAW_ROW_CAP", 2)
    set_authenticated_raw_row_cap(db_session, None, updated_by=None)

    assert _points(test_client).status_code == 400
