"""Integration tests for the run trash: `DELETE /runs/{id}` moves a run to the trash
instead of deleting it; `GET /runs/trash`, `POST /runs/{id}/restore` and
`DELETE /runs/trash/{id}` list, restore and permanently delete trashed runs. A trashed run and its
data are invisible to every other read path, public ones included.
"""

import hashlib
import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Device
from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from app.models.run import Run
from app.models.user import User
from tests.integration.campaign_helpers import create_campaign
from tests.integration.test_api.test_run_editing import FIX, _add_run, _headers

RUNS_URL = "/runs"
TRASH_URL = "/runs/trash"
BBOX = "13.0,52.0,13.5,52.5"
DEVICE_KEY = "key"
DEVICE_HEADERS = {"X-Device-ID": "device-1", "X-Device-Key": DEVICE_KEY}


@pytest.fixture
def admin(db_session: Session, test_client: TestClient) -> dict:
    return _headers(db_session, test_client, superuser=True)


@pytest.fixture
def regular(db_session: Session, test_client: TestClient) -> dict:
    return _headers(db_session, test_client, superuser=False)


def _admin_id(db_session: Session) -> int:
    return db_session.scalar(select(User.id).where(User.email == "admin-user"))


def _stored(db_session: Session, run_pk: int) -> Run | None:
    db_session.expire_all()
    return db_session.get(Run, run_pk)


def _row_counts(db_session: Session) -> tuple[int, int]:
    db_session.expire_all()
    return (
        db_session.scalar(select(func.count()).select_from(Measurement)),
        db_session.scalar(select(func.count()).select_from(LatencyTestResult)),
    )


def _trash(test_client: TestClient, admin: dict, run: Run) -> None:
    response = test_client.delete(f"{RUNS_URL}/{run.id}", headers=admin)
    assert response.status_code == 204, response.text


def _listed_run_ids(test_client: TestClient, headers: dict, **params) -> list[str]:
    response = test_client.get(RUNS_URL, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return sorted(run["run_id"] for run in response.json()["runs"])


def _trashed(test_client: TestClient, admin: dict) -> list[dict]:
    response = test_client.get(TRASH_URL, headers=admin)
    assert response.status_code == 200, response.text
    return response.json()["runs"]


# --- Authorization -------------------------------------------------------------------------


def test_trash_endpoints_require_authentication(test_client: TestClient, db_session: Session):
    run = _add_run(db_session, "run-a")

    responses = [
        test_client.get(TRASH_URL),
        test_client.post(f"{RUNS_URL}/{run.id}/restore"),
        test_client.delete(f"{TRASH_URL}/{run.id}"),
    ]

    assert [r.status_code for r in responses] == [401, 401, 401]


def test_trash_endpoints_are_forbidden_for_non_superusers(
    test_client: TestClient, db_session: Session, admin: dict, regular: dict
):
    run = _add_run(db_session, "run-a")
    _trash(test_client, admin, run)

    responses = [
        test_client.get(TRASH_URL, headers=regular),
        test_client.post(f"{RUNS_URL}/{run.id}/restore", headers=regular),
        test_client.delete(f"{TRASH_URL}/{run.id}", headers=regular),
    ]

    assert [r.status_code for r in responses] == [403, 403, 403]
    assert _stored(db_session, run.id).deleted_at is not None


# --- DELETE /runs/{id} moves to the trash ------------------------------------------------------


def test_delete_moves_the_run_to_the_trash_and_keeps_its_data(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a", points=3, latency_results=2)
    before = datetime.now(UTC)

    _trash(test_client, admin, run)

    stored = _stored(db_session, run.id)
    assert stored is not None
    assert stored.deleted_at >= before
    assert stored.deleted_by == _admin_id(db_session)
    assert _row_counts(db_session) == (3, 2)


def test_delete_of_a_trashed_run_is_404(test_client: TestClient, db_session: Session, admin: dict):
    run = _add_run(db_session, "run-a")
    _trash(test_client, admin, run)
    deleted_at = _stored(db_session, run.id).deleted_at

    response = test_client.delete(f"{RUNS_URL}/{run.id}", headers=admin)

    assert response.status_code == 404
    assert _stored(db_session, run.id).deleted_at == deleted_at


def test_delete_logs_moving_the_run_to_the_trash(
    test_client: TestClient, db_session: Session, admin: dict, caplog: pytest.LogCaptureFixture
):
    run = _add_run(db_session, "run-a")

    with caplog.at_level(logging.INFO):
        _trash(test_client, admin, run)

    message = next(r.getMessage() for r in caplog.records if "moved run" in r.getMessage())
    assert f"run_id={run.id}" in message
    assert f"user_id={_admin_id(db_session)}" in message


# --- GET /runs/trash ----------------------------------------------------------------------------


def test_trash_lists_only_trashed_runs_with_who_deleted_them_and_when(
    test_client: TestClient, db_session: Session, admin: dict
):
    campaign = create_campaign(db_session, "August")
    trashed = _add_run(db_session, "run-a", points=3, latency_results=2)
    trashed.name = "Morning drive"
    trashed.campaign_id = campaign.id
    db_session.commit()
    _add_run(db_session, "run-b")
    _trash(test_client, admin, trashed)

    runs = _trashed(test_client, admin)

    assert len(runs) == 1
    entry = runs[0]
    assert entry["id"] == trashed.id
    assert entry["run_id"] == "run-a"
    assert entry["device_id"] == "device-1"
    assert entry["name"] == "Morning drive"
    assert entry["mission_type"] == "ground"
    assert (entry["campaign_id"], entry["campaign_name"]) == (campaign.id, "August")
    assert (entry["point_count"], entry["latency_result_count"]) == (3, 2)
    assert entry["start"] == entry["end"] == "2026-08-01T12:00:00Z"
    assert entry["deleted_by"] == _admin_id(db_session)
    assert entry["deleted_by_email"] == "admin-user"
    assert entry["deleted_at"] is not None
    assert entry["legacy"] is False


def test_trash_entry_keeps_the_run_when_the_deleting_user_is_removed(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")
    _trash(test_client, admin, run)
    other_admin = _headers_of_second_admin(db_session, test_client)
    db_session.delete(db_session.get(User, _admin_id(db_session)))
    db_session.commit()

    [entry] = _trashed(test_client, other_admin)

    assert (entry["deleted_by"], entry["deleted_by_email"]) == (None, None)


def _headers_of_second_admin(db_session: Session, test_client: TestClient) -> dict:
    user = db_session.scalar(select(User).where(User.email == "admin-user"))
    db_session.add(
        User(
            email="second-admin",
            hashed_password=user.hashed_password,
            is_active=True,
            is_superuser=True,
            is_verified=False,
        )
    )
    db_session.commit()
    response = test_client.post(
        "/auth/login",
        data={"username": "second-admin", "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_trash_lists_runs_without_measurements(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "latency-only", points=0, latency_results=1)
    _trash(test_client, admin, run)

    [entry] = _trashed(test_client, admin)

    assert (entry["point_count"], entry["latency_result_count"]) == (0, 1)
    assert entry["start"] is None and entry["end"] is None


def test_trash_lists_the_most_recently_deleted_first_and_paginates(
    test_client: TestClient, db_session: Session, admin: dict
):
    for run_id in ("run-a", "run-b", "run-c"):
        _trash(test_client, admin, _add_run(db_session, run_id))

    first = test_client.get(TRASH_URL, params={"page_size": 2}, headers=admin).json()
    second = test_client.get(TRASH_URL, params={"page_size": 2, "page": 2}, headers=admin).json()

    assert [r["run_id"] for r in first["runs"]] == ["run-c", "run-b"]
    assert [r["run_id"] for r in second["runs"]] == ["run-a"]
    assert first["total"] == second["total"] == 3


# --- POST /runs/{id}/restore --------------------------------------------------------------------


def test_restore_brings_the_run_back(test_client: TestClient, db_session: Session, admin: dict):
    run = _add_run(db_session, "run-a", points=3)
    _trash(test_client, admin, run)

    response = test_client.post(f"{RUNS_URL}/{run.id}/restore", headers=admin)

    assert response.status_code == 204, response.text
    stored = _stored(db_session, run.id)
    assert (stored.deleted_at, stored.deleted_by) == (None, None)
    assert _listed_run_ids(test_client, admin) == ["run-a"]
    assert _trashed(test_client, admin) == []


def test_restore_of_a_run_that_is_not_in_the_trash_is_404(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")

    assert test_client.post(f"{RUNS_URL}/{run.id}/restore", headers=admin).status_code == 404
    assert test_client.post(f"{RUNS_URL}/999999/restore", headers=admin).status_code == 404


# --- DELETE /runs/trash/{id} --------------------------------------------------------------------


def test_permanent_delete_removes_the_run_with_its_data(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a", points=3, latency_results=2)
    other = _add_run(db_session, "run-b", points=1, latency_results=1)
    _trash(test_client, admin, run)

    response = test_client.delete(f"{TRASH_URL}/{run.id}", headers=admin)

    assert response.status_code == 204, response.text
    assert _stored(db_session, run.id) is None
    assert _stored(db_session, other.id) is not None
    assert _row_counts(db_session) == (1, 1)
    assert db_session.get(Device, "device-1") is not None


def test_permanent_delete_only_works_on_trashed_runs(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")

    assert test_client.delete(f"{TRASH_URL}/{run.id}", headers=admin).status_code == 404
    assert test_client.delete(f"{TRASH_URL}/999999", headers=admin).status_code == 404
    assert _stored(db_session, run.id) is not None


def test_permanent_delete_logs_who_deleted_which_run_without_measurement_contents(
    test_client: TestClient, db_session: Session, admin: dict, caplog: pytest.LogCaptureFixture
):
    run = _add_run(db_session, "run-a", points=3)
    _trash(test_client, admin, run)

    with caplog.at_level(logging.INFO):
        test_client.delete(f"{TRASH_URL}/{run.id}", headers=admin)

    message = next(
        r.getMessage() for r in caplog.records if "permanently deleted run" in r.getMessage()
    )
    assert f"run_id={run.id}" in message
    assert "device_id=device-1" in message
    assert "points=3" in message
    assert f"user_id={_admin_id(db_session)}" in message
    assert "rsrp" not in message


def test_a_device_reuploading_a_permanently_deleted_run_recreates_it(
    test_client: TestClient, db_session: Session, admin: dict
):
    _register_device(db_session)
    run = _add_run(db_session, "run-a")
    _trash(test_client, admin, run)
    test_client.delete(f"{TRASH_URL}/{run.id}", headers=admin)

    response = test_client.post("/measurements", json=[_datapoint()], headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    recreated = db_session.scalars(select(Run)).one()
    assert recreated.id != run.id
    assert recreated.deleted_at is None


# --- Uploads into a trashed run -----------------------------------------------------------------


def _register_device(db_session: Session) -> None:
    db_session.add(
        Device(
            device_id="device-1",
            api_key_hash=hashlib.sha256(DEVICE_KEY.encode()).hexdigest(),
            hmac_secret="y",
        )
    )
    db_session.commit()


def _datapoint() -> dict:
    return {
        "timestamp": "2026-08-01T13:00:00Z",
        "device_id": "device-1",
        "mission_type": "ground",
        "run_id": "run-a",
        "fix": {**FIX, "num_satellites": 8},
        "cell_sample": {"rat": "LTE", "rsrp": -90.0, "rsrq": -10.0, "sinr": 12.0},
    }


def test_measurements_uploaded_into_a_trashed_run_are_stored_and_the_run_stays_trashed(
    test_client: TestClient, db_session: Session, admin: dict
):
    _register_device(db_session)
    run = _add_run(db_session, "run-a", points=2, latency_results=0)
    _trash(test_client, admin, run)

    response = test_client.post("/measurements", json=[_datapoint()], headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    assert db_session.scalar(select(func.count()).select_from(Run)) == 1
    assert _stored(db_session, run.id).deleted_at is not None
    assert db_session.scalar(
        select(func.count()).select_from(Measurement).where(Measurement.run_pk == run.id)
    ) == 3
    assert _listed_run_ids(test_client, admin) == []


def test_latency_results_uploaded_into_a_trashed_run_are_stored_and_the_run_stays_trashed(
    test_client: TestClient, db_session: Session, admin: dict
):
    _register_device(db_session)
    run = _add_run(db_session, "run-a", points=1, latency_results=0)
    _trash(test_client, admin, run)
    result = {
        "test_type": "baseline",
        "flent_test": "ping",
        "device_id": "device-1",
        "mission_type": "ground",
        "run_id": "run-a",
        "start_timestamp": "2026-08-01T13:00:00Z",
        "end_timestamp": "2026-08-01T13:01:00Z",
        "start_fix": {**FIX, "num_satellites": 8},
        "end_fix": {**FIX, "num_satellites": 8},
        "baseline_rtt_ms": 12.0,
    }

    response = test_client.post("/latency-results", json=result, headers=DEVICE_HEADERS)

    assert response.status_code in (200, 201), response.text
    assert _stored(db_session, run.id).deleted_at is not None
    assert db_session.scalar(
        select(func.count())
        .select_from(LatencyTestResult)
        .where(LatencyTestResult.run_pk == run.id)
    ) == 1


# --- Editing and campaign assignment ignore trashed runs --------------------------------------


def test_editing_a_trashed_run_is_404(test_client: TestClient, db_session: Session, admin: dict):
    run = _add_run(db_session, "run-a")
    _trash(test_client, admin, run)

    response = test_client.patch(f"{RUNS_URL}/{run.id}", json={"name": "x"}, headers=admin)

    assert response.status_code == 404
    assert _stored(db_session, run.id).name is None


def test_bulk_editing_with_a_trashed_run_fails_as_a_whole(
    test_client: TestClient, db_session: Session, admin: dict
):
    trashed = _add_run(db_session, "run-a")
    active = _add_run(db_session, "run-b")
    _trash(test_client, admin, trashed)

    response = test_client.patch(
        RUNS_URL,
        json={"ids": [trashed.id, active.id], "changes": {"name": "x"}},
        headers=admin,
    )

    assert response.status_code == 404
    assert _stored(db_session, active.id).name is None
    assert _stored(db_session, trashed.id).name is None


def test_assigning_or_unassigning_a_trashed_run_to_a_campaign_is_404(
    test_client: TestClient, db_session: Session, admin: dict
):
    campaign = create_campaign(db_session, "August")
    run = _add_run(db_session, "run-a")
    run.campaign_id = campaign.id
    db_session.commit()
    other = create_campaign(db_session, "September")
    _trash(test_client, admin, run)
    body = {"runs": [{"device_id": "device-1", "run_id": "run-a"}]}

    assign = test_client.post(f"/admin/campaigns/{other.id}/runs", json=body, headers=admin)
    unassign = test_client.post(
        f"/admin/campaigns/{campaign.id}/runs/unassign", json=body, headers=admin
    )

    assert (assign.status_code, unassign.status_code) == (404, 404)
    assert _stored(db_session, run.id).campaign_id == campaign.id


# --- Read paths exclude trashed runs ----------------------------------------------------------


@pytest.fixture
def trashed_campaign_run(test_client: TestClient, db_session: Session, admin: dict) -> dict:
    """A campaign whose only run is in the trash; the run has measurements and latency results
    inside `BBOX`."""
    campaign = create_campaign(db_session, "August")
    run = _add_run(db_session, "run-a", points=2, latency_results=1)
    run.campaign_id = campaign.id
    db_session.commit()
    measurement_ids = list(db_session.scalars(select(Measurement.id)))
    _trash(test_client, admin, run)
    return {"campaign_id": campaign.id, "measurement_ids": measurement_ids}


def test_runs_list_excludes_trashed_runs(
    test_client: TestClient, db_session: Session, admin: dict, trashed_campaign_run: dict
):
    _add_run(db_session, "run-b")

    assert _listed_run_ids(test_client, admin) == ["run-b"]
    campaign_id = trashed_campaign_run["campaign_id"]
    assert _listed_run_ids(test_client, admin, campaign_id=campaign_id) == []


def test_campaign_period_ignores_trashed_runs(
    test_client: TestClient, admin: dict, trashed_campaign_run: dict
):
    public = test_client.get("/measurements/campaigns").json()["campaigns"]
    managed = test_client.get("/admin/campaigns", headers=admin).json()["campaigns"]

    for campaigns in (public, managed):
        [campaign] = campaigns
        assert (campaign["start"], campaign["end"]) == (None, None)


@pytest.mark.parametrize(
    "url, params",
    [
        ("/measurements/heatmap", {"bbox": BBOX, "metric": "rsrp"}),
        ("/measurements/points", {"bbox": BBOX, "metric": "rsrp"}),
        ("/latency-results/heatmap", {"bbox": BBOX, "metric": "baseline_rtt_ms"}),
        ("/latency-results/points", {"bbox": BBOX, "metric": "baseline_rtt_ms"}),
    ],
)
@pytest.mark.parametrize("explicit_campaign", [False, True])
def test_public_map_features_exclude_trashed_runs(
    test_client: TestClient,
    trashed_campaign_run: dict,
    url: str,
    params: dict,
    explicit_campaign: bool,
):
    if explicit_campaign:
        params = {**params, "campaign_id": trashed_campaign_run["campaign_id"]}

    response = test_client.get(url, params=params)

    assert response.status_code == 200, response.text
    assert response.json()["features"] == []


@pytest.mark.parametrize(
    "url, metric",
    [("/measurements/extent", "rsrp"), ("/latency-results/extent", "baseline_rtt_ms")],
)
@pytest.mark.parametrize("explicit_campaign", [False, True])
def test_public_extent_excludes_trashed_runs(
    test_client: TestClient,
    trashed_campaign_run: dict,
    url: str,
    metric: str,
    explicit_campaign: bool,
):
    params = {"metric": metric}
    if explicit_campaign:
        params["campaign_id"] = trashed_campaign_run["campaign_id"]

    response = test_client.get(url, params=params)

    assert response.status_code == 200, response.text
    assert response.json()["bbox"] is None


@pytest.mark.parametrize("explicit_campaign", [False, True])
def test_public_export_excludes_trashed_runs(
    test_client: TestClient, trashed_campaign_run: dict, explicit_campaign: bool
):
    params = {"bbox": BBOX, "metric": "rsrp", "format": "csv"}
    if explicit_campaign:
        params["campaign_id"] = trashed_campaign_run["campaign_id"]

    response = test_client.get("/measurements/export", params=params)

    assert response.status_code == 200, response.text
    assert response.text.strip().splitlines() == ["latitude,longitude,rsrp,count"]


@pytest.mark.parametrize("logged_in", [False, True])
def test_selection_export_excludes_trashed_runs(
    test_client: TestClient,
    admin: dict,
    trashed_campaign_run: dict,
    logged_in: bool,
):
    response = test_client.post(
        "/measurements/export-selection",
        json={"ids": trashed_campaign_run["measurement_ids"], "format": "csv"},
        headers=admin if logged_in else {},
    )

    assert response.status_code == 200, response.text
    assert len(response.text.strip().splitlines()) == 1


@pytest.mark.parametrize("view", ["aggregate", "raw"])
def test_authenticated_detailed_view_excludes_trashed_runs(
    test_client: TestClient, admin: dict, trashed_campaign_run: dict, view: str
):
    for params in ({}, {"run_id": "run-a"}):
        response = test_client.get(
            "/measurements/detailed",
            params={"bbox": BBOX, "metric": "rsrp", "view": view, **params},
            headers=admin,
        )

        assert response.status_code == 200, response.text
        assert response.json()["features"] == []


def test_authenticated_latency_raw_view_excludes_trashed_runs(
    test_client: TestClient, admin: dict, trashed_campaign_run: dict
):
    for params in ({}, {"run_id": "run-a"}):
        response = test_client.get(
            "/latency-results/raw",
            params={"bbox": BBOX, "metric": "baseline_rtt_ms", **params},
            headers=admin,
        )

        assert response.status_code == 200, response.text
        assert response.json()["features"] == []


def test_default_campaign_skips_campaigns_whose_runs_are_all_trashed(
    test_client: TestClient, db_session: Session, admin: dict
):
    older = create_campaign(db_session, "older")
    newer = create_campaign(db_session, "newer")
    kept = _add_run(db_session, "run-old", points=1, latency_results=0)
    kept.campaign_id = older.id
    trashed = _add_run(db_session, "run-new", points=1, latency_results=0)
    trashed.campaign_id = newer.id
    db_session.query(Measurement).filter(Measurement.run_pk == kept.id).update(
        {Measurement.timestamp: datetime(2026, 7, 1, tzinfo=UTC)}
    )
    db_session.commit()
    _trash(test_client, admin, trashed)

    response = test_client.get("/measurements/heatmap", params={"bbox": BBOX, "metric": "rsrp"})

    assert response.status_code == 200, response.text
    assert len(response.json()["features"]) == 1
