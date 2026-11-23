"""Integration tests for the authenticated `GET /measurements/detailed` endpoint:
an "all time" aggregate view and a raw-data view on top of the public heatmap's grid aggregation.

Needs a real Postgres (grid aggregation runs as a SQL GROUP BY query) - see
tests/integration/conftest.py for the test_client/db_session fixtures, and
tests/integration/test_api/test_campaigns.py for the auth-header-setup pattern.
"""
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from app.app_settings import set_authenticated_raw_row_cap
from app.measurements_query import RAW_ROW_CAP
from app.models.campaign import Campaign
from app.models.measurement import Measurement
from app.models.user import User
from tests.integration.campaign_helpers import date_window_campaign
from tests.integration.run_helpers import run_row

password_helper = PasswordHelper()

DETAILED_URL = "/measurements/detailed"
BERLIN_BBOX = "13.0,52.0,13.5,52.5"


def _measurement(
    lat: float,
    lon: float,
    device_id: str = "device-1",
    rsrp: float | None = -95.0,
    placeholder: bool = False,
    mission_type: str = "ground",
    timestamp: datetime = datetime(2026, 8, 1, tzinfo=UTC),
    run_id: str | None = None,
) -> Measurement:
    return run_row(
        Measurement,
        timestamp=timestamp,
        device_id=device_id,
        mission_type=mission_type,
        run_id=run_id,
        latitude=lat,
        longitude=lon,
        placeholder=placeholder,
        rsrp=rsrp,
        rsrq=-10.0,
        sinr=12.0,
        rat="LTE",
        raw_data={"secret_field": "must-never-leak"},
    )


def _campaign(db_session: Session, name: str, start_date: date, end_date: date) -> Campaign:
    return date_window_campaign(db_session, name, start_date, end_date)


def _create_user(
    db_session: Session, username: str = "regular-user", superuser: bool = False
) -> None:
    db_session.add(
        User(
            email=username,
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=superuser,
            is_verified=False,
        )
    )
    db_session.commit()


def _login(test_client: TestClient, username: str) -> str:
    response = test_client.post(
        "/auth/login",
        data={"username": username, "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _set_cap(db_session: Session, value: int | None) -> None:
    set_authenticated_raw_row_cap(db_session, value, updated_by=None)


def _auth_headers(
    db_session: Session, test_client: TestClient, username: str = "regular-user"
) -> dict:
    _create_user(db_session, username)
    return {"Authorization": f"Bearer {_login(test_client, username)}"}


# --- Auth gate ---------------------------------------------------------------


def test_detailed_requires_auth():
    from fastapi.testclient import TestClient as _TestClient

    from app.main import app

    response = _TestClient(app).get(
        DETAILED_URL, params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "aggregate"}
    )

    assert response.status_code == 401


def test_detailed_allows_any_active_user_not_just_superuser(test_client, db_session):
    headers = _auth_headers(db_session, test_client)

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "aggregate"},
        headers=headers,
    )

    assert response.status_code == 200


# --- aggregate view ------------------------------------------------------------


def test_detailed_aggregate_defaults_to_all_time_not_a_default_campaign(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    # Deliberately outside any campaign's range - a public caller would see nothing, an
    # authenticated caller with no campaign_id should see it anyway ("all time").
    _campaign(db_session, "unrelated-campaign", date(2020, 1, 1), date(2020, 1, 31))
    db_session.add(_measurement(52.1, 13.1, rsrp=-90.0, timestamp=datetime(2026, 8, 1, tzinfo=UTC)))
    db_session.commit()

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "aggregate"},
        headers=headers,
    )

    body = response.json()
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["value"] == -90.0


def test_detailed_aggregate_scopes_to_explicit_campaign(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
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
        DETAILED_URL,
        params={
            "bbox": BERLIN_BBOX,
            "metric": "rsrp",
            "view": "aggregate",
            "campaign_id": summer.id,
        },
        headers=headers,
    )

    body = response.json()
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["value"] == -90.0


def test_detailed_aggregate_response_never_includes_device_id(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    db_session.add(_measurement(52.1, 13.1, device_id="secret-device"))
    db_session.commit()

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "aggregate"},
        headers=headers,
    )

    assert "secret-device" not in response.text


# --- raw view --------------------------------------------------------------------


def test_detailed_raw_returns_individual_rows_with_device_id_and_timestamp(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    db_session.add_all(
        [
            _measurement(52.1, 13.1, device_id="device-1", rsrp=-90.0),
            _measurement(52.2, 13.2, device_id="device-1", rsrp=-95.0),
        ]
    )
    db_session.commit()

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "raw"},
        headers=headers,
    )

    body = response.json()
    assert len(body["features"]) == 2
    for feature in body["features"]:
        assert feature["properties"]["device_id"] == "device-1"
        assert "timestamp" in feature["properties"]


def test_detailed_raw_includes_every_metric_column_not_just_the_selected_one(
    test_client, db_session
):
    headers = _auth_headers(db_session, test_client)
    db_session.add(_measurement(52.1, 13.1, device_id="device-1", rsrp=-90.0))
    db_session.commit()

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "raw"},
        headers=headers,
    )

    properties = response.json()["features"][0]["properties"]
    # _measurement fixes rsrq/sinr regardless of the rsrp passed in - asserting against those
    # fixed values here, not against the "metric" query param (rsrp), confirms the other two
    # columns ride along even though only rsrp was selected for coloring/filtering.
    assert properties["rsrp"] == -90.0
    assert properties["rsrq"] == -10.0
    assert properties["sinr"] == 12.0


def test_detailed_raw_never_includes_raw_data_secret(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    db_session.add(_measurement(52.1, 13.1))
    db_session.commit()

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "raw"},
        headers=headers,
    )

    assert "must-never-leak" not in response.text


def test_detailed_raw_excludes_placeholder_rows(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    db_session.add(_measurement(52.1, 13.1, placeholder=True))
    db_session.commit()

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "raw"},
        headers=headers,
    )

    assert response.json()["features"] == []


def test_detailed_raw_is_unlimited_by_default_for_logged_in_users(
    test_client, db_session, monkeypatch
):
    headers = _auth_headers(db_session, test_client)
    monkeypatch.setattr("app.measurements_query.RAW_ROW_CAP", 2)
    db_session.add_all(
        [_measurement(52.1, 13.1, device_id=f"device-{i}", rsrp=-90.0) for i in range(3)]
    )
    db_session.commit()

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "raw"},
        headers=headers,
    )

    assert response.status_code == 200
    assert len(response.json()["features"]) == 3


def test_detailed_raw_returns_more_rows_than_the_guest_cap_by_default(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    db_session.add_all(
        [_measurement(52.1, 13.1, device_id=f"device-{i}") for i in range(RAW_ROW_CAP + 1)]
    )
    db_session.commit()

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "raw"},
        headers=headers,
    )

    assert response.status_code == 200
    assert len(response.json()["features"]) == RAW_ROW_CAP + 1


def test_detailed_raw_enforces_the_configured_cap_at_query_level(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    _set_cap(db_session, 2)
    db_session.add_all(
        [_measurement(52.1, 13.1, device_id=f"device-{i}", rsrp=-90.0) for i in range(3)]
    )
    db_session.commit()

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "raw"},
        headers=headers,
    )

    assert response.status_code == 400


def test_detailed_raw_under_the_configured_cap_succeeds(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    _set_cap(db_session, 3)
    db_session.add_all(
        [_measurement(52.1, 13.1, device_id=f"device-{i}", rsrp=-90.0) for i in range(3)]
    )
    db_session.commit()

    response = test_client.get(
        DETAILED_URL,
        params={"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "raw"},
        headers=headers,
    )

    assert response.status_code == 200
    assert len(response.json()["features"]) == 3


def test_raw_row_cap_is_a_concrete_bounded_value():
    assert 0 < RAW_ROW_CAP <= 50_000
