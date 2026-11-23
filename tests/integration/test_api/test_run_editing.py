"""Integration tests for editing and deleting runs: `PATCH /runs/{id}`, the bulk
`PATCH /runs` and `DELETE /runs/{id}`, all superuser-only.
"""
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Device
from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from app.models.run import Run
from app.models.user import User
from tests.integration.campaign_helpers import create_campaign
from tests.integration.run_helpers import run_row

password_helper = PasswordHelper()

RUNS_URL = "/runs"
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
FIX = {"position": {"latitude": 52.1, "longitude": 13.1}, "placeholder": False}


def _headers(db_session: Session, test_client: TestClient, superuser: bool) -> dict:
    email = "admin-user" if superuser else "regular-user"
    db_session.add(
        User(
            email=email,
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=superuser,
            is_verified=False,
        )
    )
    db_session.commit()
    response = test_client.post(
        "/auth/login", data={"username": email, "password": "correct-horse-battery-staple"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin(db_session: Session, test_client: TestClient) -> dict:
    return _headers(db_session, test_client, superuser=True)


def _add_run(
    db_session: Session,
    run_id: str,
    device_id: str = "device-1",
    mission_type: str = "ground",
    points: int = 2,
    latency_results: int = 1,
) -> Run:
    if db_session.get(Device, device_id) is None:
        db_session.add(Device(device_id=device_id, api_key_hash="x", hmac_secret="x"))
        db_session.flush()
    db_session.add_all(
        run_row(
            Measurement,
            timestamp=NOW,
            device_id=device_id,
            run_id=run_id,
            mission_type=mission_type,
            latitude=52.1,
            longitude=13.1,
            placeholder=False,
            rsrp=-90.0,
            raw_data={},
        )
        for _ in range(points)
    )
    db_session.add_all(
        run_row(
            LatencyTestResult,
            device_id=device_id,
            run_id=run_id,
            mission_type=mission_type,
            test_type="baseline",
            flent_test="rrul",
            start_timestamp=NOW,
            end_timestamp=NOW,
            start_fix=FIX,
            end_fix=FIX,
            baseline_rtt_ms=40.0,
            idempotency_key=f"{device_id}-{run_id}-{i}",
        )
        for i in range(latency_results)
    )
    db_session.commit()
    return db_session.scalars(
        select(Run).where(Run.device_id == device_id, Run.run_id == run_id)
    ).one()


def _stored(db_session: Session, run: Run) -> Run:
    db_session.expire_all()
    return db_session.get(Run, run.id)


def _row_counts(db_session: Session) -> tuple[int, int]:
    db_session.expire_all()
    return (
        db_session.scalar(select(func.count()).select_from(Measurement)),
        db_session.scalar(select(func.count()).select_from(LatencyTestResult)),
    )


# --- Authorization -------------------------------------------------------------------------


def test_editing_and_deleting_require_authentication(
    test_client: TestClient, db_session: Session
):
    run = _add_run(db_session, "run-a")

    assert test_client.patch(f"{RUNS_URL}/{run.id}", json={"name": "x"}).status_code == 401
    assert (
        test_client.patch(RUNS_URL, json={"ids": [run.id], "changes": {"name": "x"}}).status_code
        == 401
    )
    assert test_client.delete(f"{RUNS_URL}/{run.id}").status_code == 401
    assert _stored(db_session, run).name is None
    assert _row_counts(db_session) == (2, 1)


def test_editing_and_deleting_are_forbidden_for_non_superusers(
    test_client: TestClient, db_session: Session
):
    run = _add_run(db_session, "run-a")
    headers = _headers(db_session, test_client, superuser=False)

    patch = test_client.patch(f"{RUNS_URL}/{run.id}", json={"name": "x"}, headers=headers)
    bulk = test_client.patch(
        RUNS_URL, json={"ids": [run.id], "changes": {"name": "x"}}, headers=headers
    )
    delete = test_client.delete(f"{RUNS_URL}/{run.id}", headers=headers)

    assert (patch.status_code, bulk.status_code, delete.status_code) == (403, 403, 403)
    assert _stored(db_session, run).name is None
    assert _row_counts(db_session) == (2, 1)


# --- PATCH /runs/{id} ------------------------------------------------------------------------


def test_patch_updates_name_mission_type_and_campaign(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")
    campaign = create_campaign(db_session, "august")

    response = test_client.patch(
        f"{RUNS_URL}/{run.id}",
        json={"name": "Morning flight", "mission_type": "drone", "campaign_id": campaign.id},
        headers=admin,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": run.id,
        "device_id": "device-1",
        "run_id": "run-a",
        "name": "Morning flight",
        "mission_type": "drone",
        "campaign_id": campaign.id,
        "campaign_name": "august",
    }
    stored = _stored(db_session, run)
    assert (stored.name, stored.mission_type, stored.campaign_id) == (
        "Morning flight",
        "drone",
        campaign.id,
    )


def test_patch_changes_only_the_fields_that_are_sent(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a", mission_type="drone")
    campaign = create_campaign(db_session, "august")
    run.name = "Keep me"
    run.campaign_id = campaign.id
    db_session.commit()

    response = test_client.patch(
        f"{RUNS_URL}/{run.id}", json={"mission_type": "ground"}, headers=admin
    )

    assert response.status_code == 200, response.text
    stored = _stored(db_session, run)
    assert (stored.name, stored.mission_type, stored.campaign_id) == (
        "Keep me",
        "ground",
        campaign.id,
    )


def test_patch_with_null_clears_name_and_campaign(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")
    campaign = create_campaign(db_session, "august")
    run.name = "Old"
    run.campaign_id = campaign.id
    db_session.commit()

    response = test_client.patch(
        f"{RUNS_URL}/{run.id}", json={"name": None, "campaign_id": None}, headers=admin
    )

    assert response.status_code == 200, response.text
    stored = _stored(db_session, run)
    assert (stored.name, stored.campaign_id) == (None, None)


def test_patch_trims_the_name_and_treats_a_blank_one_as_cleared(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")

    trimmed = test_client.patch(f"{RUNS_URL}/{run.id}", json={"name": "  Lap 1 "}, headers=admin)
    assert trimmed.json()["name"] == "Lap 1"

    blank = test_client.patch(f"{RUNS_URL}/{run.id}", json={"name": "   "}, headers=admin)
    assert blank.json()["name"] is None


def test_patch_does_not_touch_the_measurements_of_the_run(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")

    test_client.patch(f"{RUNS_URL}/{run.id}", json={"mission_type": "drone"}, headers=admin)

    db_session.expire_all()
    assert set(db_session.scalars(select(Measurement.run_pk))) == {run.id}
    assert set(db_session.scalars(select(LatencyTestResult.run_pk))) == {run.id}


def test_patch_of_an_unknown_run_is_404(test_client: TestClient, db_session: Session, admin: dict):
    response = test_client.patch(f"{RUNS_URL}/999999", json={"name": "x"}, headers=admin)

    assert response.status_code == 404


def test_patch_with_an_unknown_campaign_is_404_and_changes_nothing(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")

    response = test_client.patch(
        f"{RUNS_URL}/{run.id}", json={"name": "x", "campaign_id": 999999}, headers=admin
    )

    assert response.status_code == 404
    assert _stored(db_session, run).name is None


@pytest.mark.parametrize(
    "body",
    [
        {"mission_type": "boat"},
        {"mission_type": None},
        {"mission_type": ""},
        {"name": "x" * 256},
        {"name": "line\nbreak"},
        {"name": "tab\there"},
        {"name": "nul\x00byte"},
        {"name": 5},
        {"campaign_id": "abc"},
        {"device_id": "other"},
        {"run_id": "other"},
        {"id": 5},
        {"name": "ok", "point_count": 3},
        {},
    ],
)
def test_patch_rejects_invalid_bodies_without_changing_anything(
    test_client: TestClient, db_session: Session, admin: dict, body: dict
):
    run = _add_run(db_session, "run-a")

    response = test_client.patch(f"{RUNS_URL}/{run.id}", json=body, headers=admin)

    assert response.status_code == 422, response.text
    stored = _stored(db_session, run)
    assert (stored.device_id, stored.run_id, stored.name, stored.mission_type) == (
        "device-1",
        "run-a",
        None,
        "ground",
    )


def test_patch_rejects_a_non_integer_id(test_client: TestClient, admin: dict):
    response = test_client.patch(f"{RUNS_URL}/abc", json={"name": "x"}, headers=admin)

    assert response.status_code == 422


# --- PATCH /runs (bulk) ------------------------------------------------------------------


def test_bulk_patch_applies_the_changes_to_every_selected_run_only(
    test_client: TestClient, db_session: Session, admin: dict
):
    first = _add_run(db_session, "run-a")
    second = _add_run(db_session, "run-b", device_id="device-2")
    untouched = _add_run(db_session, "run-c")
    campaign = create_campaign(db_session, "august")

    response = test_client.patch(
        RUNS_URL,
        json={
            "ids": [first.id, second.id],
            "changes": {"mission_type": "drone", "campaign_id": campaign.id},
        },
        headers=admin,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"updated": 2}
    assert _stored(db_session, first).mission_type == "drone"
    assert _stored(db_session, second).campaign_id == campaign.id
    assert _stored(db_session, untouched).mission_type == "ground"
    assert _stored(db_session, untouched).campaign_id is None


def test_bulk_patch_only_changes_the_fields_in_changes(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")
    run.name = "Keep me"
    db_session.commit()

    test_client.patch(
        RUNS_URL,
        json={"ids": [run.id], "changes": {"mission_type": "drone"}},
        headers=admin,
    )

    stored = _stored(db_session, run)
    assert (stored.name, stored.mission_type) == ("Keep me", "drone")


def test_bulk_patch_deduplicates_ids(test_client: TestClient, db_session: Session, admin: dict):
    run = _add_run(db_session, "run-a")

    response = test_client.patch(
        RUNS_URL,
        json={"ids": [run.id, run.id, run.id], "changes": {"name": "Once"}},
        headers=admin,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"updated": 1}


def test_bulk_patch_with_one_unknown_id_fails_as_a_whole(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")

    response = test_client.patch(
        RUNS_URL,
        json={"ids": [run.id, 999999], "changes": {"name": "x", "mission_type": "drone"}},
        headers=admin,
    )

    assert response.status_code == 404
    assert str(999999) not in response.text
    stored = _stored(db_session, run)
    assert (stored.name, stored.mission_type) == (None, "ground")


def test_bulk_patch_with_an_unknown_campaign_fails_as_a_whole(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")

    response = test_client.patch(
        RUNS_URL,
        json={"ids": [run.id], "changes": {"name": "x", "campaign_id": 999999}},
        headers=admin,
    )

    assert response.status_code == 404
    assert _stored(db_session, run).name is None


def test_bulk_patch_can_unassign_runs_from_their_campaign(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")
    run.campaign_id = create_campaign(db_session, "august").id
    db_session.commit()

    test_client.patch(
        RUNS_URL, json={"ids": [run.id], "changes": {"campaign_id": None}}, headers=admin
    )

    assert _stored(db_session, run).campaign_id is None


@pytest.mark.parametrize(
    "body",
    [
        {"ids": [], "changes": {"name": "x"}},
        {"ids": [1], "changes": {}},
        {"ids": [1]},
        {"changes": {"name": "x"}},
        {"ids": list(range(1, 502)), "changes": {"name": "x"}},
        {"ids": [0], "changes": {"name": "x"}},
        {"ids": [-1], "changes": {"name": "x"}},
        {"ids": ["abc"], "changes": {"name": "x"}},
        {"ids": [1], "changes": {"mission_type": "boat"}},
        {"ids": [1], "changes": {"mission_type": None}},
        {"ids": [1], "changes": {"name": "x" * 256}},
        {"ids": [1], "changes": {"name": "bad\nname"}},
        {"ids": [1], "changes": {"device_id": "other"}},
        {"ids": [1], "changes": {"run_id": "other"}},
        {"ids": [1], "changes": {"id": 2}},
        {"ids": [1], "changes": {"name": "x"}, "device_id": "other"},
    ],
)
def test_bulk_patch_rejects_invalid_bodies(
    test_client: TestClient, db_session: Session, admin: dict, body: dict
):
    run = _add_run(db_session, "run-a")
    body = {**body, **({"ids": [run.id]} if body.get("ids") == [1] else {})}

    response = test_client.patch(RUNS_URL, json=body, headers=admin)

    assert response.status_code == 422, response.text
    stored = _stored(db_session, run)
    assert (stored.device_id, stored.run_id, stored.name, stored.mission_type) == (
        "device-1",
        "run-a",
        None,
        "ground",
    )


def test_bulk_patch_accepts_the_maximum_number_of_ids(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")

    response = test_client.patch(
        RUNS_URL,
        json={"ids": [run.id, *range(1_000_000, 1_000_499)], "changes": {"name": "x"}},
        headers=admin,
    )

    assert response.status_code == 404  # within the size limit, so it is the unknown ids that fail


# --- DELETE /runs/{id} (moving to the trash is covered in test_run_trash.py) -------------------


def test_delete_of_an_unknown_run_is_404(test_client: TestClient, admin: dict):
    assert test_client.delete(f"{RUNS_URL}/999999", headers=admin).status_code == 404


# --- GET /runs ------------------------------------------------------------------------------


def test_the_runs_list_returns_id_name_and_the_mission_type_of_the_run(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")
    test_client.patch(
        f"{RUNS_URL}/{run.id}", json={"name": "Flight", "mission_type": "drone"}, headers=admin
    )

    body = test_client.get(RUNS_URL, headers=admin).json()

    [listed] = body["runs"]
    assert (listed["id"], listed["name"], listed["mission_type"]) == (run.id, "Flight", "drone")


def test_the_mission_type_filter_uses_the_edited_mission_type(
    test_client: TestClient, db_session: Session, admin: dict
):
    run = _add_run(db_session, "run-a")
    _add_run(db_session, "run-b")
    test_client.patch(f"{RUNS_URL}/{run.id}", json={"mission_type": "drone"}, headers=admin)

    body = test_client.get(RUNS_URL, params={"mission_type": "drone"}, headers=admin).json()

    assert [r["run_id"] for r in body["runs"]] == ["run-a"]
