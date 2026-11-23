"""Integration tests for superuser campaign CRUD (app/routers/campaigns.py) and the public
campaign listing (`GET /measurements/campaigns`, app/routers/measurements.py).

Needs a real Postgres - see tests/integration/conftest.py for the test_client/db_session
fixtures used here, and tests/integration/test_api/test_devices.py for the
superuser-header-setup pattern this file follows.
"""
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from app.models import Device
from app.models.campaign import Campaign
from app.models.measurement import Measurement
from app.models.run import Run
from app.models.user import User

password_helper = PasswordHelper()

CAMPAIGNS_URL = "/admin/campaigns"


def _create_superuser(db_session: Session, username: str = "admin-user") -> None:
    db_session.add(
        User(
            email=username,
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=True,
            is_verified=False,
        )
    )
    db_session.commit()


def _login(test_client: TestClient, username: str = "admin-user") -> str:
    response = test_client.post(
        "/auth/login",
        data={"username": username, "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _superuser_headers(db_session: Session, test_client: TestClient) -> dict:
    _create_superuser(db_session)
    return {"Authorization": f"Bearer {_login(test_client)}"}


def _campaign(db_session: Session, name: str) -> Campaign:
    campaign = Campaign(name=name)
    db_session.add(campaign)
    db_session.commit()
    db_session.refresh(campaign)
    return campaign


def _run(
    db_session: Session,
    run_id: str,
    first: datetime,
    last: datetime | None = None,
    device_id: str = "device-1",
    campaign: Campaign | None = None,
) -> None:
    """A run with a `runs` row and measurements at `first` (and `last`)."""
    run = Run(
        device_id=device_id,
        run_id=run_id,
        mission_type="ground",
        campaign_id=campaign and campaign.id,
    )
    db_session.add(run)
    db_session.flush()
    for timestamp in (first, last or first):
        db_session.add(
            Measurement(
                timestamp=timestamp,
                device_id=device_id,
                run_pk=run.id,
                latitude=52.1,
                longitude=13.1,
                placeholder=False,
                rsrp=-90.0,
                raw_data={},
            )
        )
    db_session.commit()


def _assigned_campaigns(db_session: Session) -> dict[tuple[str, str], str | None]:
    db_session.expire_all()
    names = {c.id: c.name for c in db_session.query(Campaign)}
    return {
        (run.device_id, run.run_id): names.get(run.campaign_id)
        for run in db_session.query(Run)
    }


def _ref(run_id: str, device_id: str = "device-1") -> dict:
    return {"device_id": device_id, "run_id": run_id}


def day(month: int, d: int, hour: int = 12) -> datetime:
    return datetime(2026, month, d, hour, tzinfo=UTC)


# --- GET /admin/campaigns ---------------------------------------------------


def test_list_campaigns_requires_auth(test_client):
    response = test_client.get(CAMPAIGNS_URL)

    assert response.status_code == 401


def test_list_campaigns_rejects_non_superuser(test_client, db_session):
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
    token = _login(test_client, "regular-user")

    response = test_client.get(CAMPAIGNS_URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_list_campaigns_derives_the_period_from_the_oldest_and_newest_run(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "run-a", day(6, 10), day(6, 10, 14), campaign=campaign)
    _run(db_session, "run-b", day(8, 20), day(8, 21), campaign=campaign)
    _run(db_session, "run-c", day(7, 1), campaign=campaign)
    _run(db_session, "other-campaign-run", day(1, 1))

    response = test_client.get(CAMPAIGNS_URL, headers=headers)

    assert response.status_code == 200
    [listed] = response.json()["campaigns"]
    assert listed["name"] == "summer-2026"
    assert listed["start"] == "2026-06-10"
    assert listed["end"] == "2026-08-21"
    assert set(listed) == {"id", "name", "start", "end"}


def test_list_campaigns_has_no_period_while_a_campaign_has_no_runs(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _campaign(db_session, "empty")

    [listed] = test_client.get(CAMPAIGNS_URL, headers=headers).json()["campaigns"]

    assert listed["start"] is None
    assert listed["end"] is None


def test_list_campaigns_orders_by_period_with_empty_campaigns_last(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    empty = _campaign(db_session, "a-empty")
    later = _campaign(db_session, "later")
    earlier = _campaign(db_session, "earlier")
    _run(db_session, "run-later", day(9, 1), campaign=later)
    _run(db_session, "run-earlier", day(3, 1), campaign=earlier)
    assert empty.id

    campaigns = test_client.get(CAMPAIGNS_URL, headers=headers).json()["campaigns"]

    assert [c["name"] for c in campaigns] == ["earlier", "later", "a-empty"]


# --- POST /admin/campaigns ---------------------------------------------------


def test_create_campaign_requires_auth(test_client):
    response = test_client.post(CAMPAIGNS_URL, json={"name": "summer-2026"})

    assert response.status_code == 401


def test_create_campaign_success_creates_an_empty_campaign(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.post(CAMPAIGNS_URL, json={"name": "summer-2026"}, headers=headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "summer-2026"
    assert "id" in body
    assert body["start"] is None
    assert body["end"] is None


def test_create_campaign_rejects_invalid_name(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.post(CAMPAIGNS_URL, json={"name": "Summer 2026!"}, headers=headers)

    assert response.status_code == 422


def test_create_campaign_rejects_name_over_max_length(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.post(CAMPAIGNS_URL, json={"name": "a" * 64}, headers=headers)

    assert response.status_code == 422


def test_create_campaign_rejects_duplicate_name(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _campaign(db_session, "summer-2026")

    response = test_client.post(CAMPAIGNS_URL, json={"name": "summer-2026"}, headers=headers)

    assert response.status_code == 400


# --- PATCH /admin/campaigns/{id} ---------------------------------------------------


def test_update_campaign_requires_auth(test_client, db_session):
    campaign = _campaign(db_session, "summer-2026")

    response = test_client.patch(f"{CAMPAIGNS_URL}/{campaign.id}", json={"name": "renamed"})

    assert response.status_code == 401


def test_update_campaign_renames_and_keeps_the_runs(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "run-a", day(6, 10), campaign=campaign)

    response = test_client.patch(
        f"{CAMPAIGNS_URL}/{campaign.id}", json={"name": "summer-2026-renamed"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "summer-2026-renamed"
    assert response.json()["start"] == "2026-06-10"


def test_update_campaign_with_its_own_name_does_not_conflict(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")

    response = test_client.patch(
        f"{CAMPAIGNS_URL}/{campaign.id}", json={"name": "summer-2026"}, headers=headers
    )

    assert response.status_code == 200


def test_update_campaign_rejects_a_name_taken_by_another_campaign(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _campaign(db_session, "summer-2026")
    winter = _campaign(db_session, "winter-2026")

    response = test_client.patch(
        f"{CAMPAIGNS_URL}/{winter.id}", json={"name": "summer-2026"}, headers=headers
    )

    assert response.status_code == 400


def test_update_campaign_not_found(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.patch(
        f"{CAMPAIGNS_URL}/999999", json={"name": "does-not-exist"}, headers=headers
    )

    assert response.status_code == 404


# --- DELETE /admin/campaigns/{id} ---------------------------------------------------


def test_delete_campaign_requires_auth(test_client, db_session):
    campaign = _campaign(db_session, "summer-2026")

    response = test_client.delete(f"{CAMPAIGNS_URL}/{campaign.id}")

    assert response.status_code == 401


def test_delete_campaign_success(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")

    response = test_client.delete(f"{CAMPAIGNS_URL}/{campaign.id}", headers=headers)

    assert response.status_code == 204
    assert test_client.get(CAMPAIGNS_URL, headers=headers).json()["campaigns"] == []


def test_delete_campaign_unassigns_its_runs_but_keeps_them(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "run-a", day(6, 10), campaign=campaign)

    test_client.delete(f"{CAMPAIGNS_URL}/{campaign.id}", headers=headers)

    assert _assigned_campaigns(db_session) == {("device-1", "run-a"): None}


def test_delete_campaign_not_found(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.delete(f"{CAMPAIGNS_URL}/999999", headers=headers)

    assert response.status_code == 404


# --- POST /admin/campaigns/{id}/runs ---------------------------------------------------


def _assign_url(campaign: Campaign) -> str:
    return f"{CAMPAIGNS_URL}/{campaign.id}/runs"


def _unassign_url(campaign: Campaign) -> str:
    return f"{CAMPAIGNS_URL}/{campaign.id}/runs/unassign"


def test_assign_runs_requires_auth(test_client, db_session):
    campaign = _campaign(db_session, "summer-2026")

    response = test_client.post(_assign_url(campaign), json={"runs": [_ref("run-a")]})

    assert response.status_code == 401


def test_assign_runs_rejects_non_superuser(test_client, db_session):
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "run-a", day(6, 10))
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
    token = _login(test_client, "regular-user")

    response = test_client.post(
        _assign_url(campaign),
        json={"runs": [_ref("run-a")]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert _assigned_campaigns(db_session) == {("device-1", "run-a"): None}


def test_assign_runs_adds_them_and_returns_the_updated_period(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "run-a", day(6, 10), day(6, 11))
    _run(db_session, "run-b", day(8, 20))
    _run(db_session, "run-untouched", day(1, 1))

    response = test_client.post(
        _assign_url(campaign), json={"runs": [_ref("run-a"), _ref("run-b")]}, headers=headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start"] == "2026-06-10"
    assert body["end"] == "2026-08-20"
    assert _assigned_campaigns(db_session) == {
        ("device-1", "run-a"): "summer-2026",
        ("device-1", "run-b"): "summer-2026",
        ("device-1", "run-untouched"): None,
    }


def test_assign_runs_moves_a_run_out_of_its_previous_campaign(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    old = _campaign(db_session, "old")
    new = _campaign(db_session, "new")
    _run(db_session, "run-a", day(6, 10), campaign=old)

    response = test_client.post(_assign_url(new), json={"runs": [_ref("run-a")]}, headers=headers)

    assert response.status_code == 200
    assert _assigned_campaigns(db_session) == {("device-1", "run-a"): "new"}
    [old_listed] = [
        c for c in test_client.get(CAMPAIGNS_URL, headers=headers).json()["campaigns"]
        if c["name"] == "old"
    ]
    assert old_listed["start"] is None


def test_assign_runs_is_idempotent_and_accepts_duplicates(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "run-a", day(6, 10))

    for _ in range(2):
        response = test_client.post(
            _assign_url(campaign), json={"runs": [_ref("run-a"), _ref("run-a")]}, headers=headers
        )
        assert response.status_code == 200, response.text

    assert _assigned_campaigns(db_session) == {("device-1", "run-a"): "summer-2026"}


def test_assign_runs_distinguishes_devices_with_the_same_run_id(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "shared", day(6, 10), device_id="device-1")
    _run(db_session, "shared", day(6, 11), device_id="device-2")

    test_client.post(
        _assign_url(campaign), json={"runs": [_ref("shared", "device-2")]}, headers=headers
    )

    assert _assigned_campaigns(db_session) == {
        ("device-1", "shared"): None,
        ("device-2", "shared"): "summer-2026",
    }


def test_assign_runs_with_an_unknown_run_changes_nothing(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "run-a", day(6, 10))

    response = test_client.post(
        _assign_url(campaign),
        json={"runs": [_ref("run-a"), _ref("does-not-exist")]},
        headers=headers,
    )

    assert response.status_code == 404
    assert "does-not-exist" not in response.text
    assert "device-1" not in response.text
    assert _assigned_campaigns(db_session) == {("device-1", "run-a"): None}


def test_assign_runs_to_an_unknown_campaign_is_404(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    _run(db_session, "run-a", day(6, 10))

    response = test_client.post(
        f"{CAMPAIGNS_URL}/999999/runs", json={"runs": [_ref("run-a")]}, headers=headers
    )

    assert response.status_code == 404


def test_assign_runs_validates_the_request_body(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")

    for body in ({"runs": []}, {}, {"runs": [{"run_id": "run-a"}]}, {"runs": [_ref("")]}):
        response = test_client.post(_assign_url(campaign), json=body, headers=headers)
        assert response.status_code == 422, body


def test_assign_runs_rejects_too_many_runs_in_one_request(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")
    runs = [_ref(f"run-{i}") for i in range(501)]

    response = test_client.post(_assign_url(campaign), json={"runs": runs}, headers=headers)

    assert response.status_code == 422


# --- POST /admin/campaigns/{id}/runs/unassign ---------------------------------------------------


def test_unassign_runs_requires_auth(test_client, db_session):
    campaign = _campaign(db_session, "summer-2026")

    response = test_client.post(_unassign_url(campaign), json={"runs": [_ref("run-a")]})

    assert response.status_code == 401


def test_unassign_runs_removes_them_from_the_campaign(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "run-a", day(6, 10), campaign=campaign)
    _run(db_session, "run-b", day(8, 20), campaign=campaign)

    response = test_client.post(
        _unassign_url(campaign), json={"runs": [_ref("run-b")]}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["end"] == "2026-06-10"
    assert _assigned_campaigns(db_session) == {
        ("device-1", "run-a"): "summer-2026",
        ("device-1", "run-b"): None,
    }


def test_unassigning_the_last_run_empties_the_period(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "run-a", day(6, 10), campaign=campaign)

    response = test_client.post(
        _unassign_url(campaign), json={"runs": [_ref("run-a")]}, headers=headers
    )

    assert response.json()["start"] is None
    assert response.json()["end"] is None


def test_unassign_runs_of_another_campaign_is_404_and_changes_nothing(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    campaign = _campaign(db_session, "summer-2026")
    other = _campaign(db_session, "other")
    _run(db_session, "run-a", day(6, 10), campaign=campaign)
    _run(db_session, "run-b", day(6, 11), campaign=other)

    response = test_client.post(
        _unassign_url(campaign),
        json={"runs": [_ref("run-a"), _ref("run-b")]},
        headers=headers,
    )

    assert response.status_code == 404
    assert _assigned_campaigns(db_session) == {
        ("device-1", "run-a"): "summer-2026",
        ("device-1", "run-b"): "other",
    }


def test_unassign_runs_from_an_unknown_campaign_is_404(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.post(
        f"{CAMPAIGNS_URL}/999999/runs/unassign", json={"runs": [_ref("run-a")]}, headers=headers
    )

    assert response.status_code == 404


# --- GET /measurements/campaigns (public) ---------------------------------------------------


def test_public_campaign_listing_does_not_require_authentication(test_client, db_session):
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "run-a", day(6, 10), day(6, 12), campaign=campaign)

    response = test_client.get("/measurements/campaigns")

    assert response.status_code == 200
    [listed] = response.json()["campaigns"]
    assert listed["name"] == "summer-2026"
    assert listed["start"] == "2026-06-10"
    assert listed["end"] == "2026-06-12"


def test_public_campaign_period_is_whole_utc_days_without_a_time_of_day(test_client, db_session):
    campaign = _campaign(db_session, "summer-2026")
    _run(db_session, "run-a", day(6, 10, 23), day(6, 11, 1), campaign=campaign)

    [listed] = test_client.get("/measurements/campaigns").json()["campaigns"]

    assert listed["start"] == "2026-06-10"
    assert listed["end"] == "2026-06-11"


def test_public_campaign_listing_exposes_only_id_name_and_period(test_client, db_session):
    campaign = _campaign(db_session, "summer-2026")
    db_session.add(Device(device_id="device-1", api_key_hash="x", hmac_secret="x"))
    _run(db_session, "secret-run-id", day(6, 10), campaign=campaign)

    response = test_client.get("/measurements/campaigns")

    assert set(response.json()["campaigns"][0]) == {"id", "name", "start", "end"}
    assert "secret-run-id" not in response.text
    assert "device-1" not in response.text


def test_public_campaign_listing_empty_when_none_configured(test_client, db_session):
    response = test_client.get("/measurements/campaigns")

    assert response.status_code == 200
    assert response.json()["campaigns"] == []
