"""Integration tests for the public `GET /measurements/points` endpoint: raw
per-measurement points for anonymous visitors, structurally without device_id/timestamp.

Needs a real Postgres - see tests/integration/conftest.py and test_measurements_detailed.py
for the fixtures and row helpers reused here.
"""

from datetime import UTC, date, datetime

from app.app_settings import set_authenticated_raw_row_cap
from tests.integration.test_api.test_measurements_detailed import (
    BERLIN_BBOX,
    _campaign,
    _measurement,
)

POINTS_URL = "/measurements/points"
FORBIDDEN_KEYS = {"device_id", "timestamp", "run_id", "raw_data"}


def _year_campaign(db_session):
    return _campaign(db_session, "All", date(2026, 1, 1), date(2026, 12, 31))


def _get(test_client, **params):
    return test_client.get(POINTS_URL, params={"bbox": BERLIN_BBOX, "metric": "rsrp", **params})


def test_points_is_public_and_returns_position_and_all_three_metrics(test_client, db_session):
    _year_campaign(db_session)
    measurement = _measurement(52.1, 13.1)
    db_session.add(measurement)
    db_session.commit()

    response = _get(test_client)

    assert response.status_code == 200
    [feature] = response.json()["features"]
    assert feature["geometry"] == {"type": "Point", "coordinates": [13.1, 52.1]}
    assert feature["properties"] == {
        "id": measurement.id,
        "rsrp": -95.0,
        "rsrq": -10.0,
        "sinr": 12.0,
    }


def test_points_response_never_contains_identifying_keys(test_client, db_session):
    _year_campaign(db_session)
    db_session.add(_measurement(52.1, 13.1, device_id="secret-device"))
    db_session.commit()

    response = _get(test_client)

    body = response.text
    assert "secret-device" not in body
    assert "must-never-leak" not in body
    [feature] = response.json()["features"]
    assert FORBIDDEN_KEYS.isdisjoint(feature["properties"])
    assert FORBIDDEN_KEYS.isdisjoint(feature)


def test_points_ignores_device_id_param(test_client, db_session):
    _year_campaign(db_session)
    db_session.add_all(
        [
            _measurement(52.1, 13.1, device_id="device-a"),
            _measurement(52.2, 13.2, device_id="device-b"),
        ]
    )
    db_session.commit()

    response = _get(test_client, device_id="device-a")

    assert len(response.json()["features"]) == 2


def test_points_excludes_placeholder_rows(test_client, db_session):
    _year_campaign(db_session)
    db_session.add_all([_measurement(52.1, 13.1), _measurement(52.2, 13.2, placeholder=True)])
    db_session.commit()

    response = _get(test_client)

    assert len(response.json()["features"]) == 1


def test_points_gates_rows_on_selected_metric_and_bbox(test_client, db_session):
    _year_campaign(db_session)
    db_session.add_all(
        [
            _measurement(52.1, 13.1),
            _measurement(52.2, 13.2, rsrp=None),
            _measurement(10.0, 10.0),
        ]
    )
    db_session.commit()

    response = _get(test_client)

    assert len(response.json()["features"]) == 1


def test_points_filters_by_mission_type(test_client, db_session):
    _year_campaign(db_session)
    db_session.add_all(
        [
            _measurement(52.1, 13.1, mission_type="ground"),
            _measurement(52.2, 13.2, mission_type="drone"),
        ]
    )
    db_session.commit()

    response = _get(test_client, mission_type="drone")

    assert len(response.json()["features"]) == 1


def test_points_defaults_to_most_recent_campaign_and_never_blends(test_client, db_session):
    _campaign(db_session, "Old", date(2026, 1, 1), date(2026, 1, 31))
    newer = _campaign(db_session, "Newer", date(2026, 2, 1), date(2026, 2, 28))
    db_session.add_all(
        [
            _measurement(52.1, 13.1, timestamp=datetime(2026, 1, 15, tzinfo=UTC)),
            _measurement(52.2, 13.2, timestamp=datetime(2026, 2, 15, tzinfo=UTC)),
        ]
    )
    db_session.commit()

    default = _get(test_client)
    explicit = _get(test_client, campaign_id=newer.id)

    assert default.json() == explicit.json()
    assert len(default.json()["features"]) == 1


def test_points_with_no_campaigns_returns_nothing(test_client, db_session):
    db_session.add(_measurement(52.1, 13.1))
    db_session.commit()

    response = _get(test_client)

    assert response.status_code == 200
    assert response.json()["features"] == []


def test_points_unknown_campaign_is_404(test_client):
    assert _get(test_client, campaign_id=99999).status_code == 404


def test_points_400_when_row_cap_exceeded(test_client, db_session, monkeypatch):
    monkeypatch.setattr("app.measurements_query.RAW_ROW_CAP", 2)
    _year_campaign(db_session)
    db_session.add_all([_measurement(52.1 + i * 0.001, 13.1) for i in range(3)])
    db_session.commit()

    response = _get(test_client)

    assert response.status_code == 400


def test_points_stay_capped_when_the_authenticated_cap_is_unlimited(
    test_client, db_session, monkeypatch
):
    monkeypatch.setattr("app.measurements_query.RAW_ROW_CAP", 2)
    _year_campaign(db_session)
    db_session.add_all([_measurement(52.1 + i * 0.001, 13.1) for i in range(3)])
    db_session.commit()
    set_authenticated_raw_row_cap(db_session, None, updated_by=None)

    assert _get(test_client).status_code == 400


def test_authenticated_detailed_endpoint_is_unchanged(test_client, db_session):
    from tests.integration.test_api.test_measurements_detailed import DETAILED_URL, _auth_headers

    db_session.add(_measurement(52.1, 13.1))
    db_session.commit()
    headers = _auth_headers(db_session, test_client)

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "raw"},
        headers=headers,
    )

    [feature] = response.json()["features"]
    assert feature["properties"]["device_id"] == "device-1"
    assert "timestamp" in feature["properties"]
