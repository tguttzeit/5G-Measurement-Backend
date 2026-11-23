"""Integration tests for `GET /runs`: runs listed from `measurements` grouped by
(device_id, run_id), visible to any logged-in user, with filters, sorting and pagination.
"""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from app.models.measurement import Measurement
from app.models.user import User
from tests.integration.campaign_helpers import assign_runs, create_campaign
from tests.integration.run_helpers import run_row

RUNS_URL = "/runs"
password_helper = PasswordHelper()


def _measurement(
    run_id: str,
    timestamp: datetime,
    device_id: str = "device-1",
    mission_type: str = "ground",
    rsrp: float | None = -90.0,
    rsrq: float | None = -10.0,
    sinr: float | None = 10.0,
) -> Measurement:
    return run_row(
        Measurement,
        timestamp=timestamp,
        device_id=device_id,
        mission_type=mission_type,
        run_id=run_id,
        latitude=52.5,
        longitude=13.4,
        placeholder=False,
        rsrp=rsrp,
        rsrq=rsrq,
        sinr=sinr,
        rat="LTE",
        raw_data={},
    )


def _add(db_session: Session, *measurements: Measurement) -> None:
    db_session.add_all(measurements)
    db_session.commit()


def _run_points(run_id: str, start: datetime, count: int, minutes_apart: int = 1, **kwargs):
    return [
        _measurement(run_id, start + timedelta(minutes=i * minutes_apart), **kwargs)
        for i in range(count)
    ]


def _auth_headers(db_session: Session, test_client: TestClient) -> dict:
    db_session.add(
        User(
            email="regular-user",
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
    )
    db_session.commit()
    response = test_client.post(
        "/auth/login",
        data={"username": "regular-user", "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _list_runs(test_client: TestClient, headers: dict, **params) -> dict:
    response = test_client.get(RUNS_URL, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _run_ids(body: dict) -> list[str]:
    return [run["run_id"] for run in body["runs"]]


# --- Auth gate ---------------------------------------------------------------


def test_runs_requires_authentication(test_client: TestClient):
    assert test_client.get(RUNS_URL).status_code == 401


def test_runs_is_available_to_non_superusers(test_client: TestClient, db_session: Session):
    headers = _auth_headers(db_session, test_client)

    assert test_client.get(RUNS_URL, headers=headers).status_code == 200


# --- Listing -----------------------------------------------------------------


def test_runs_are_grouped_per_device_and_run_id_with_aggregates(
    test_client: TestClient, db_session: Session
):
    start = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    _add(
        db_session,
        _measurement("run-a", start, rsrp=-100.0, rsrq=-12.0, sinr=4.0),
        _measurement("run-a", start + timedelta(minutes=30), rsrp=-80.0, rsrq=-8.0, sinr=8.0),
        _measurement("run-a", start + timedelta(minutes=10), rsrp=None, rsrq=None, sinr=None),
        _measurement("run-a", start + timedelta(minutes=5), device_id="device-2"),
    )
    headers = _auth_headers(db_session, test_client)

    body = _list_runs(test_client, headers)

    assert body["total"] == 2
    run = next(r for r in body["runs"] if r["device_id"] == "device-1")
    assert run["run_id"] == "run-a"
    assert run["mission_type"] == "ground"
    assert run["start"] == "2026-08-01T10:00:00Z"
    assert run["end"] == "2026-08-01T10:30:00Z"
    assert run["point_count"] == 3
    assert run["mean_rsrp"] == -90.0
    assert run["mean_rsrq"] == -10.0
    assert run["mean_sinr"] == 6.0
    assert run["legacy"] is False


def test_runs_without_any_metric_values_report_null_means(
    test_client: TestClient, db_session: Session
):
    _add(
        db_session,
        _measurement("run-a", datetime(2026, 8, 1, tzinfo=UTC), rsrp=None, rsrq=None, sinr=None),
    )

    run = _list_runs(test_client, _auth_headers(db_session, test_client))["runs"][0]

    assert (run["mean_rsrp"], run["mean_rsrq"], run["mean_sinr"]) == (None, None, None)


def test_legacy_runs_are_flagged(test_client: TestClient, db_session: Session):
    _add(
        db_session,
        _measurement("legacy-device-1-ground-2026-08-01", datetime(2026, 8, 1, tzinfo=UTC)),
    )

    run = _list_runs(test_client, _auth_headers(db_session, test_client))["runs"][0]

    assert run["legacy"] is True


def test_run_ids_shared_by_two_devices_are_listed_as_two_runs(
    test_client: TestClient, db_session: Session
):
    start = datetime(2026, 8, 1, tzinfo=UTC)
    _add(
        db_session,
        _measurement("shared", start, device_id="device-1"),
        _measurement("shared", start, device_id="device-2"),
    )

    body = _list_runs(test_client, _auth_headers(db_session, test_client))

    assert {(r["device_id"], r["run_id"]) for r in body["runs"]} == {
        ("device-1", "shared"),
        ("device-2", "shared"),
    }


def test_each_run_reports_the_campaign_it_is_assigned_to(
    test_client: TestClient, db_session: Session
):
    august = create_campaign(db_session, "august")
    _add(
        db_session,
        _measurement("in-august", datetime(2026, 8, 31, 23, 59, tzinfo=UTC)),
        _measurement("no-campaign", datetime(2026, 9, 15, tzinfo=UTC)),
        _measurement("also-no-campaign", datetime(2026, 9, 16, tzinfo=UTC)),
    )
    assign_runs(db_session, august, ("device-1", "in-august"))

    body = _list_runs(test_client, _auth_headers(db_session, test_client))
    runs = {r["run_id"]: r for r in body["runs"]}

    assert runs["in-august"]["campaign_name"] == "august"
    assert runs["in-august"]["campaign_id"] == august.id
    for unassigned in ("no-campaign", "also-no-campaign"):
        assert runs[unassigned]["campaign_id"] is None
        assert runs[unassigned]["campaign_name"] is None


def test_a_run_outside_the_campaign_time_span_is_still_listed_with_its_campaign(
    test_client: TestClient, db_session: Session
):
    campaign = create_campaign(db_session, "mixed")
    _add(
        db_session,
        _measurement("january", datetime(2026, 1, 5, tzinfo=UTC)),
        _measurement("october", datetime(2026, 10, 5, tzinfo=UTC)),
    )
    assign_runs(db_session, campaign, ("device-1", "january"), ("device-1", "october"))

    body = _list_runs(test_client, _auth_headers(db_session, test_client))

    assert {r["run_id"]: r["campaign_name"] for r in body["runs"]} == {
        "january": "mixed",
        "october": "mixed",
    }


# --- Filters -----------------------------------------------------------------


def test_filters_by_device_id_and_mission_type(test_client: TestClient, db_session: Session):
    start = datetime(2026, 8, 1, tzinfo=UTC)
    _add(
        db_session,
        _measurement("a", start, device_id="device-1", mission_type="ground"),
        _measurement("b", start, device_id="device-1", mission_type="drone"),
        _measurement("c", start, device_id="device-2", mission_type="ground"),
    )
    headers = _auth_headers(db_session, test_client)

    assert _run_ids(_list_runs(test_client, headers, device_id="device-2")) == ["c"]
    assert _run_ids(_list_runs(test_client, headers, mission_type="drone")) == ["b"]
    both = _list_runs(test_client, headers, device_id="device-1", mission_type="ground")
    assert _run_ids(both) == ["a"]


def test_filters_by_campaign_equality_not_by_time(test_client: TestClient, db_session: Session):
    campaign = create_campaign(db_session, "august")
    other = create_campaign(db_session, "other")
    _add(
        db_session,
        _measurement("inside", datetime(2026, 8, 31, 23, 0, tzinfo=UTC)),
        _measurement("assigned-elsewhere-in-time", datetime(2026, 8, 15, tzinfo=UTC)),
        _measurement("far-away-but-assigned", datetime(2025, 1, 1, tzinfo=UTC)),
        _measurement("unassigned", datetime(2026, 8, 20, tzinfo=UTC)),
    )
    assign_runs(
        db_session,
        campaign,
        ("device-1", "inside"),
        ("device-1", "far-away-but-assigned"),
    )
    assign_runs(db_session, other, ("device-1", "assigned-elsewhere-in-time"))
    headers = _auth_headers(db_session, test_client)

    body = _list_runs(test_client, headers, campaign_id=campaign.id)

    assert sorted(_run_ids(body)) == ["far-away-but-assigned", "inside"]
    assert body["total"] == 2


def test_filters_by_unassigned_runs(test_client: TestClient, db_session: Session):
    campaign = create_campaign(db_session, "august")
    _add(
        db_session,
        _measurement("assigned", datetime(2026, 8, 1, tzinfo=UTC)),
        _measurement("unassigned-a", datetime(2026, 8, 2, tzinfo=UTC)),
        _measurement("unassigned-b", datetime(2026, 8, 3, tzinfo=UTC)),
    )
    assign_runs(db_session, campaign, ("device-1", "assigned"))
    headers = _auth_headers(db_session, test_client)

    body = _list_runs(test_client, headers, unassigned="true")

    assert sorted(_run_ids(body)) == ["unassigned-a", "unassigned-b"]


def test_unassigned_and_campaign_id_cannot_be_combined(
    test_client: TestClient, db_session: Session
):
    campaign = create_campaign(db_session, "august")
    headers = _auth_headers(db_session, test_client)

    response = test_client.get(
        RUNS_URL, params={"campaign_id": campaign.id, "unassigned": "true"}, headers=headers
    )

    assert response.status_code == 400


def test_unknown_campaign_id_is_404(test_client: TestClient, db_session: Session):
    headers = _auth_headers(db_session, test_client)

    response = test_client.get(RUNS_URL, params={"campaign_id": 999}, headers=headers)

    assert response.status_code == 404


def test_filters_by_inclusive_utc_date_range_of_the_run_start(
    test_client: TestClient, db_session: Session
):
    _add(
        db_session,
        _measurement("jul-31", datetime(2026, 7, 31, 23, 59, tzinfo=UTC)),
        _measurement("aug-1", datetime(2026, 8, 1, 0, 0, tzinfo=UTC)),
        _measurement("aug-2", datetime(2026, 8, 2, 23, 59, tzinfo=UTC)),
        _measurement("aug-3", datetime(2026, 8, 3, 0, 0, tzinfo=UTC)),
    )
    headers = _auth_headers(db_session, test_client)

    body = _list_runs(test_client, headers, **{"from": "2026-08-01", "to": "2026-08-02"})

    assert sorted(_run_ids(body)) == ["aug-1", "aug-2"]


def test_a_malformed_date_filter_is_422(test_client: TestClient, db_session: Session):
    headers = _auth_headers(db_session, test_client)

    response = test_client.get(RUNS_URL, params={"from": "yesterday"}, headers=headers)

    assert response.status_code == 422


# --- Sorting -----------------------------------------------------------------


def test_default_order_is_newest_start_first(test_client: TestClient, db_session: Session):
    _add(
        db_session,
        _measurement("old", datetime(2026, 8, 1, tzinfo=UTC)),
        _measurement("new", datetime(2026, 8, 3, tzinfo=UTC)),
        _measurement("mid", datetime(2026, 8, 2, tzinfo=UTC)),
    )

    body = _list_runs(test_client, _auth_headers(db_session, test_client))

    assert _run_ids(body) == ["new", "mid", "old"]


def test_sorts_by_duration_and_point_count_in_either_direction(
    test_client: TestClient, db_session: Session
):
    start = datetime(2026, 8, 1, tzinfo=UTC)
    _add(
        db_session,
        *_run_points("long-few", start, 2, minutes_apart=60),
        *_run_points("short-many", start, 5, minutes_apart=1),
    )
    headers = _auth_headers(db_session, test_client)

    assert _run_ids(_list_runs(test_client, headers, sort="duration", order="desc")) == [
        "long-few",
        "short-many",
    ]
    assert _run_ids(_list_runs(test_client, headers, sort="duration", order="asc")) == [
        "short-many",
        "long-few",
    ]
    assert _run_ids(_list_runs(test_client, headers, sort="point_count", order="desc")) == [
        "short-many",
        "long-few",
    ]


def test_an_unknown_sort_key_is_422(test_client: TestClient, db_session: Session):
    headers = _auth_headers(db_session, test_client)

    response = test_client.get(RUNS_URL, params={"sort": "device_id; drop table"}, headers=headers)

    assert response.status_code == 422


# --- Pagination --------------------------------------------------------------


def test_pagination_returns_the_requested_page_and_the_unpaged_total(
    test_client: TestClient, db_session: Session
):
    start = datetime(2026, 8, 1, tzinfo=UTC)
    _add(db_session, *[_measurement(f"run-{i}", start + timedelta(days=i)) for i in range(5)])
    headers = _auth_headers(db_session, test_client)

    page_two = _list_runs(test_client, headers, page=2, page_size=2)

    assert page_two["total"] == 5
    assert (page_two["page"], page_two["page_size"]) == (2, 2)
    assert _run_ids(page_two) == ["run-2", "run-1"]


def test_page_size_has_a_maximum(test_client: TestClient, db_session: Session):
    headers = _auth_headers(db_session, test_client)

    assert test_client.get(RUNS_URL, params={"page_size": 101}, headers=headers).status_code == 422
    assert test_client.get(RUNS_URL, params={"page_size": 0}, headers=headers).status_code == 422
    assert test_client.get(RUNS_URL, params={"page": 0}, headers=headers).status_code == 422


def test_an_empty_database_lists_no_runs(test_client: TestClient, db_session: Session):
    body = _list_runs(test_client, _auth_headers(db_session, test_client))

    assert body == {"runs": [], "total": 0, "page": 1, "page_size": 25}
