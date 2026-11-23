"""Integration tests for the `/measurements/extent` endpoint.

Needs a real Postgres - see tests/integration/conftest.py for the test_client/db_session
fixtures used here.
"""
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.measurement import Measurement
from tests.integration.campaign_helpers import date_window_campaign
from tests.integration.run_helpers import run_row


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
    return _campaign(db_session, "default-campaign", date(2026, 7, 1), date(2026, 8, 31))


def test_extent_does_not_require_authentication(test_client, db_session):
    _default_campaign(db_session)
    db_session.add(_measurement(52.1, 13.1))
    db_session.commit()

    response = test_client.get("/measurements/extent", params={"metric": "rsrp"})

    assert response.status_code == 200


def test_extent_returns_null_bbox_when_no_data(test_client, db_session):
    _default_campaign(db_session)

    response = test_client.get("/measurements/extent", params={"metric": "rsrp"})

    assert response.json()["bbox"] is None


def test_extent_returns_null_bbox_when_no_campaigns_configured(test_client, db_session):
    db_session.add(_measurement(52.1, 13.1))
    db_session.commit()

    response = test_client.get("/measurements/extent", params={"metric": "rsrp"})

    assert response.json()["bbox"] is None


def test_extent_returns_true_min_max_not_a_grid_cell_center(test_client, db_session):
    """Regression: a tight, asymmetric cluster near one edge of a grid cell must
    report its own real extent, not a cell-center-derived box - the whole point of this endpoint
    is sidestepping the heatmap's grid aggregation for this use case."""
    _default_campaign(db_session)
    db_session.add_all(
        [
            _measurement(48.349285, 10.869938),
            _measurement(48.359996, 10.878011),
        ]
    )
    db_session.commit()

    response = test_client.get("/measurements/extent", params={"metric": "rsrp"})

    bbox = response.json()["bbox"]
    assert bbox == [10.869938, 48.349285, 10.878011, 48.359996]


def test_extent_excludes_placeholder_gps_rows(test_client, db_session):
    _default_campaign(db_session)
    db_session.add(_measurement(52.1, 13.1, placeholder=True))
    db_session.commit()

    response = test_client.get("/measurements/extent", params={"metric": "rsrp"})

    assert response.json()["bbox"] is None


def test_extent_excludes_rows_where_requested_metric_is_null(test_client, db_session):
    _default_campaign(db_session)
    m = _measurement(52.1, 13.1)
    m.sinr = None
    db_session.add(m)
    db_session.commit()

    response = test_client.get("/measurements/extent", params={"metric": "sinr"})

    assert response.json()["bbox"] is None


def test_extent_filters_by_device_id(test_client, db_session):
    _default_campaign(db_session)
    db_session.add_all(
        [
            _measurement(52.1, 13.1, device_id="device-1"),
            _measurement(60.0, 20.0, device_id="device-2"),
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/extent", params={"metric": "rsrp", "device_id": "device-1"}
    )

    assert response.json()["bbox"] == [13.1, 52.1, 13.1, 52.1]


def test_extent_filters_by_mission_type(test_client, db_session):
    _default_campaign(db_session)
    db_session.add_all(
        [
            _measurement(52.1, 13.1, mission_type="ground"),
            _measurement(60.0, 20.0, mission_type="drone"),
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/extent", params={"metric": "rsrp", "mission_type": "drone"}
    )

    assert response.json()["bbox"] == [20.0, 60.0, 20.0, 60.0]


def test_extent_scopes_to_explicit_campaign_id(test_client, db_session):
    summer = _campaign(db_session, "summer-2026", date(2026, 7, 1), date(2026, 8, 31))
    _campaign(db_session, "winter-2026", date(2026, 12, 1), date(2027, 2, 28))
    db_session.add_all(
        [
            _measurement(52.1, 13.1, timestamp=datetime(2026, 8, 1, tzinfo=UTC)),
            _measurement(60.0, 20.0, timestamp=datetime(2026, 12, 15, tzinfo=UTC)),
        ]
    )
    db_session.commit()

    response = test_client.get(
        "/measurements/extent", params={"metric": "rsrp", "campaign_id": summer.id}
    )

    assert response.json()["bbox"] == [13.1, 52.1, 13.1, 52.1]


def test_extent_rejects_nonexistent_campaign_id(test_client, db_session):
    response = test_client.get(
        "/measurements/extent", params={"metric": "rsrp", "campaign_id": 999999}
    )

    assert response.status_code == 404


def test_extent_response_never_includes_timestamp_or_device_id(test_client, db_session):
    _default_campaign(db_session)
    db_session.add(_measurement(52.1, 13.1, device_id="secret-device"))
    db_session.commit()

    response = test_client.get("/measurements/extent", params={"metric": "rsrp"})

    body_text = response.text
    assert "secret-device" not in body_text
    assert "2026-08-01" not in body_text
