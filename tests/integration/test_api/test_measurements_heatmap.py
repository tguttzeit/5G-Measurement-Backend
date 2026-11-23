"""Integration tests for the heatmap/export map endpoints.

Needs a real Postgres (grid aggregation runs as a GROUP BY on floor(...) expressions) - see
tests/integration/conftest.py for the test_client/db_session fixtures used here.
"""
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.measurement import Measurement
from tests.integration.campaign_helpers import date_window_campaign
from tests.integration.run_helpers import run_row

BERLIN_BBOX = "13.0,52.0,13.5,52.5"


def _measurement(
    lat: float,
    lon: float,
    device_id: str = "device-1",
    rsrp: float | None = -95.0,
    placeholder: bool = False,
    mission_type: str = "ground",
    timestamp: datetime = datetime(2026, 8, 1, tzinfo=UTC),
) -> Measurement:
    return run_row(
        Measurement,
        timestamp=timestamp,
        device_id=device_id,
        mission_type=mission_type,
        latitude=lat,
        longitude=lon,
        placeholder=placeholder,
        rsrp=rsrp,
        rsrq=-10.0,
        sinr=12.0,
        rat="LTE",
        raw_data={},
    )


def _campaign(db_session: Session, name: str, start_date: date, end_date: date) -> Campaign:
    return date_window_campaign(db_session, name, start_date, end_date)


def _default_campaign(db_session: Session) -> Campaign:
    """Covers `_measurement`'s default 2026-08-01 timestamp, for tests that aren't themselves
    about campaign scoping but still need their measurements to fall inside some campaign."""
    return _campaign(db_session, "default-campaign", date(2026, 7, 1), date(2026, 8, 31))


def test_heatmap_does_not_require_authentication(test_client, db_session):
    db_session.add(_measurement(52.1, 13.1))
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": BERLIN_BBOX, "metric": "rsrp"}
    )

    assert response.status_code == 200


def test_heatmap_returns_geojson_feature_collection(test_client, db_session):
    _default_campaign(db_session)
    db_session.add(_measurement(52.1, 13.1, rsrp=-90.0))
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": BERLIN_BBOX, "metric": "rsrp"}
    )

    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    feature = body["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"
    assert feature["properties"]["value"] == -90.0
    assert feature["properties"]["count"] == 1


def test_heatmap_response_never_includes_timestamp_or_device_id(test_client, db_session):
    _default_campaign(db_session)
    db_session.add(_measurement(52.1, 13.1))
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": BERLIN_BBOX, "metric": "rsrp"}
    )

    body_text = response.text
    assert "device-1" not in body_text
    assert "2026-08-01" not in body_text


def test_heatmap_excludes_placeholder_gps_rows(test_client, db_session):
    _default_campaign(db_session)
    db_session.add(_measurement(52.1, 13.1, placeholder=True))
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": BERLIN_BBOX, "metric": "rsrp"}
    )

    assert response.json()["features"] == []


def test_heatmap_excludes_points_outside_bbox(test_client, db_session):
    _default_campaign(db_session)
    db_session.add(_measurement(60.0, 20.0))  # well outside BERLIN_BBOX
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": BERLIN_BBOX, "metric": "rsrp"}
    )

    assert response.json()["features"] == []


def test_heatmap_aggregates_nearby_points_into_one_grid_cell(test_client, db_session, monkeypatch):
    """Above POINT_RENDER_THRESHOLD, the response is grid-aggregated - see
    test_heatmap_dedups_near_duplicate_points_within_a_few_meters and
    test_heatmap_keeps_far_apart_points_distinct_below_the_render_threshold for the below-
    threshold "real points" mode this endpoint uses otherwise."""
    monkeypatch.setattr("app.measurements_query.POINT_RENDER_THRESHOLD", 1)
    _default_campaign(db_session)
    db_session.add_all(
        [
            _measurement(52.104, 13.104, rsrp=-90.0),
            _measurement(52.1045, 13.1045, rsrp=-100.0),
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": BERLIN_BBOX, "metric": "rsrp"}
    )

    body = response.json()
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["value"] == -95.0
    assert body["features"][0]["properties"]["count"] == 2


def test_heatmap_filters_by_device_id(test_client, db_session):
    _default_campaign(db_session)
    db_session.add_all(
        [
            _measurement(52.1, 13.1, device_id="device-1", rsrp=-90.0),
            _measurement(52.2, 13.2, device_id="device-2", rsrp=-70.0),
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap",
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "device_id": "device-1"},
    )

    body = response.json()
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["value"] == -90.0


def test_heatmap_filters_by_mission_type(test_client, db_session):
    _default_campaign(db_session)
    db_session.add_all(
        [
            _measurement(52.1, 13.1, mission_type="ground", rsrp=-90.0),
            _measurement(52.2, 13.2, mission_type="drone", rsrp=-70.0),
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap",
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "mission_type": "drone"},
    )

    body = response.json()
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["value"] == -70.0


def test_heatmap_scopes_to_explicit_campaign_id(test_client, db_session):
    summer = _campaign(db_session, "summer-2026", date(2026, 7, 1), date(2026, 8, 31))
    _campaign(db_session, "winter-2026", date(2026, 12, 1), date(2027, 2, 28))
    db_session.add_all(
        [
            _measurement(52.1, 13.1, rsrp=-90.0, timestamp=datetime(2026, 8, 1, tzinfo=UTC)),
            _measurement(52.2, 13.2, rsrp=-70.0, timestamp=datetime(2026, 12, 15, tzinfo=UTC)),
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap",
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "campaign_id": summer.id},
    )

    body = response.json()
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["value"] == -90.0


def test_heatmap_rejects_nonexistent_campaign_id(test_client, db_session):
    response = test_client.get(
        "/measurements/heatmap",
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "campaign_id": 999999},
    )

    assert response.status_code == 404


def test_heatmap_returns_empty_when_no_campaigns_configured(test_client, db_session):
    db_session.add(_measurement(52.1, 13.1, rsrp=-90.0))
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": BERLIN_BBOX, "metric": "rsrp"}
    )

    assert response.json()["features"] == []


def test_heatmap_ignores_free_form_date_query_params(test_client, db_session):
    """Security regression: start_date/end_date no longer exist on this endpoint - passing
    them must have zero filtering effect, or a public caller could blend two campaigns' data by
    passing a range spanning both, defeating campaign scoping via a path that was never closed.
    """
    summer = _campaign(db_session, "summer-2026", date(2026, 7, 1), date(2026, 8, 31))
    _campaign(db_session, "winter-2026", date(2026, 12, 1), date(2027, 2, 28))
    db_session.add_all(
        [
            _measurement(52.1, 13.1, rsrp=-90.0, timestamp=datetime(2026, 8, 1, tzinfo=UTC)),
            _measurement(52.2, 13.2, rsrp=-70.0, timestamp=datetime(2026, 12, 15, tzinfo=UTC)),
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap",
        params={
            "bbox": BERLIN_BBOX,
            "metric": "rsrp",
            "campaign_id": summer.id,
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-12-31T00:00:00Z",
        },
    )

    body = response.json()
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["value"] == -90.0


def test_heatmap_excludes_rows_where_requested_metric_is_null(test_client, db_session):
    _default_campaign(db_session)
    m = _measurement(52.1, 13.1, rsrp=-90.0)
    m.sinr = None
    db_session.add(m)
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": BERLIN_BBOX, "metric": "sinr"}
    )

    assert response.json()["features"] == []


def test_export_csv_returns_csv_content(test_client, db_session):
    _default_campaign(db_session)
    db_session.add(_measurement(52.1, 13.1, rsrp=-90.0))
    db_session.commit()

    response = test_client.get(
        "/measurements/export",
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "format": "csv"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert lines[0] == "latitude,longitude,rsrp,count"
    assert len(lines) == 2


def test_export_geojson_returns_feature_collection(test_client, db_session):
    _default_campaign(db_session)
    db_session.add(_measurement(52.1, 13.1, rsrp=-90.0))
    db_session.commit()

    response = test_client.get(
        "/measurements/export",
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "format": "geojson"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/geo+json")
    assert response.json()["type"] == "FeatureCollection"


def test_heatmap_cell_is_stable_across_panned_bboxes(test_client, db_session):
    """Regression: the old bbox-relative grid recomputed cell boundaries fresh
    for every request, so the same point's returned cell center (and therefore its rendered
    position/value) shifted on every pan/resize even though the underlying data never changed.
    The grid is now anchored to a fixed global origin, so a same-sized bbox shifted by a pan
    must return the exact same cell center for a point both bboxes cover."""
    _default_campaign(db_session)
    db_session.add(_measurement(52.104, 13.104, rsrp=-90.0))
    db_session.commit()

    bbox_a = "13.0,52.0,13.5,52.5"
    bbox_b = "13.05,52.02,13.55,52.52"  # same size, panned slightly - still covers the point

    response_a = test_client.get(
        "/measurements/heatmap", params={"bbox": bbox_a, "metric": "rsrp"}
    )
    response_b = test_client.get(
        "/measurements/heatmap", params={"bbox": bbox_b, "metric": "rsrp"}
    )

    features_a = response_a.json()["features"]
    features_b = response_b.json()["features"]
    assert len(features_a) == 1
    assert features_a == features_b


def test_heatmap_keeps_far_apart_points_distinct_below_the_render_threshold(
    test_client, db_session
):
    """Below POINT_RENDER_THRESHOLD, the map must show real individual points, not
    grid-aggregated cells - two measurements ~100m apart must stay two separate points, each
    with its own real value, not get blended into one averaged point."""
    _default_campaign(db_session)
    db_session.add_all(
        [
            _measurement(52.100, 13.100, rsrp=-70.0),
            _measurement(52.100, 13.101, rsrp=-110.0),  # roughly 70m away at this latitude
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": BERLIN_BBOX, "metric": "rsrp"}
    )

    values = {feature["properties"]["value"] for feature in response.json()["features"]}
    assert values == {-70.0, -110.0}


def test_heatmap_dedups_near_duplicate_points_within_a_few_meters(test_client, db_session):
    """Two readings a couple meters apart (e.g. a device stopped briefly) must be
    merged into one point even in the below-threshold "real points" mode - otherwise they'd
    stack and visually overdrive the heat layer at that one spot."""
    _default_campaign(db_session)
    db_session.add_all(
        [
            _measurement(52.100000, 13.100000, rsrp=-70.0),
            _measurement(52.100002, 13.100002, rsrp=-90.0),  # well under a meter away
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": BERLIN_BBOX, "metric": "rsrp"}
    )

    features = response.json()["features"]
    assert len(features) == 1
    assert features[0]["properties"]["value"] == -80.0
    assert features[0]["properties"]["count"] == 2


def test_heatmap_does_not_chain_merge_points_across_adjacent_dedup_cells(test_client, db_session):
    """Regression: below the render threshold, only rows landing in the exact same fine dedup
    cell are merged - a chain of points each ~2m from the next (so each lands in a cell adjacent
    to the last, but never the same one) must stay as distinct points, not cascade through
    adjacency into one merged point."""
    _default_campaign(db_session)
    # Each point lands in a different, but consecutively adjacent, dedup cell (~2.2m apart).
    db_session.add_all(
        [
            _measurement(52.0999932626662, 13.100000, rsrp=-70.0),
            _measurement(52.100015720445555, 13.100000, rsrp=-90.0),
            _measurement(52.100038178224935, 13.100000, rsrp=-110.0),
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": BERLIN_BBOX, "metric": "rsrp"}
    )

    features = response.json()["features"]
    assert len(features) == 3
    assert {feature["properties"]["value"] for feature in features} == {-70.0, -90.0, -110.0}


def test_heatmap_does_not_merge_adjacent_but_distinct_grid_cells_above_the_render_threshold(
    test_client, db_session, monkeypatch
):
    """Regression: an earlier version blob-merged touching grid cells together above
    the render threshold, transitively chaining anything spatially continuous into one or two
    giant blobs - for real (non-sparse) data that collapsed way more points than intended, not a
    useful "clustering". Two points landing in adjacent-but-distinct cells must now stay as two
    separate rendered points - only rows that land in the exact same cell are averaged together
    (via the grid's own GROUP BY, see test_heatmap_aggregates_nearby_points_into_one_grid_cell)."""
    monkeypatch.setattr("app.measurements_query.POINT_RENDER_THRESHOLD", 1)
    _default_campaign(db_session)
    db_session.add_all(
        [
            _measurement(52.10, 13.10, rsrp=-70.0),
            _measurement(52.10, 13.11, rsrp=-110.0),
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/heatmap", params={"bbox": "13.0,52.0,13.2,52.2", "metric": "rsrp"}
    )

    body = response.json()
    assert len(body["features"]) == 2
    assert {feature["properties"]["value"] for feature in body["features"]} == {-70.0, -110.0}
    assert all(feature["properties"]["count"] == 1 for feature in body["features"])


def test_export_response_never_includes_device_id(test_client, db_session):
    _default_campaign(db_session)
    db_session.add(_measurement(52.1, 13.1, device_id="secret-device"))
    db_session.commit()

    response = test_client.get(
        "/measurements/export",
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "format": "csv"},
    )

    assert "secret-device" not in response.text
