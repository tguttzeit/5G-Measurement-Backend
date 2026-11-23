"""Integration tests for the superuser-only raw-row-cap setting (`/settings/raw-row-cap`) and the
`app_settings` accessors behind it.

Needs a real Postgres - see tests/integration/conftest.py. Auth-header setup follows
tests/integration/test_api/test_campaigns.py.
"""
from sqlalchemy import select

from app.app_settings import (
    AUTHENTICATED_RAW_ROW_CAP_KEY,
    SHUTDOWN_CONFIRMATION_KEY,
    get_authenticated_raw_row_cap,
    get_shutdown_confirmation,
    set_authenticated_raw_row_cap,
)
from app.models.app_setting import AppSetting
from app.models.user import User
from app.schemas.settings import MAX_RAW_ROW_CAP, ShutdownConfirmation
from tests.integration.test_api.test_campaigns import _superuser_headers
from tests.integration.test_api.test_measurements_detailed import _auth_headers

URL = "/settings/raw-row-cap"


def test_get_requires_auth(test_client):
    assert test_client.get(URL).status_code == 401


def test_put_requires_auth(test_client):
    assert test_client.put(URL, json={"value": 10}).status_code == 401


def test_get_rejects_regular_user(test_client, db_session):
    headers = _auth_headers(db_session, test_client)

    assert test_client.get(URL, headers=headers).status_code == 403


def test_put_rejects_regular_user_and_stores_nothing(test_client, db_session):
    headers = _auth_headers(db_session, test_client)

    response = test_client.put(URL, json={"value": 10}, headers=headers)

    assert response.status_code == 403
    assert db_session.get(AppSetting, AUTHENTICATED_RAW_ROW_CAP_KEY) is None


def test_get_defaults_to_unlimited(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.get(URL, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"value": None, "updated_at": None, "updated_by": None}


def test_put_sets_the_cap_and_records_who_and_when(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.put(URL, json={"value": 1234}, headers=headers)

    body = response.json()
    assert response.status_code == 200
    assert body["value"] == 1234
    assert body["updated_at"] is not None
    assert body["updated_by"] is not None
    assert test_client.get(URL, headers=headers).json() == body


def test_put_null_restores_unlimited(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    test_client.put(URL, json={"value": 10}, headers=headers)

    response = test_client.put(URL, json={"value": None}, headers=headers)

    assert response.status_code == 200
    assert response.json()["value"] is None
    assert get_authenticated_raw_row_cap(db_session) is None


def test_put_overwrites_instead_of_adding_a_row(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    test_client.put(URL, json={"value": 10}, headers=headers)
    test_client.put(URL, json={"value": 20}, headers=headers)

    assert get_authenticated_raw_row_cap(db_session) == 20


def test_put_rejects_invalid_values_and_keeps_the_stored_one(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    test_client.put(URL, json={"value": 10}, headers=headers)

    for invalid in [0, -5, MAX_RAW_ROW_CAP + 1, 10**30, True, 5.5, "5000"]:
        response = test_client.put(URL, json={"value": invalid}, headers=headers)
        assert response.status_code == 422, invalid

    assert test_client.put(URL, json={}, headers=headers).status_code == 422
    assert get_authenticated_raw_row_cap(db_session) == 10


def test_validation_error_does_not_echo_the_submitted_input(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.put(URL, json={"value": "secret-ish"}, headers=headers)

    assert "secret-ish" not in response.text


def test_corrupted_stored_value_falls_back_to_the_default(db_session):
    db_session.add(AppSetting(key=AUTHENTICATED_RAW_ROW_CAP_KEY, value="not-a-number"))
    db_session.commit()

    assert get_authenticated_raw_row_cap(db_session) is None


def test_stored_out_of_range_value_falls_back_to_the_default(db_session):
    db_session.add(AppSetting(key=AUTHENTICATED_RAW_ROW_CAP_KEY, value=-3))
    db_session.commit()

    assert get_authenticated_raw_row_cap(db_session) is None


def test_stored_value_roundtrips_through_the_accessors(db_session, test_client):
    _superuser_headers(db_session, test_client)
    user_id = db_session.scalar(select(User.id))

    set_authenticated_raw_row_cap(db_session, 77, user_id)

    assert get_authenticated_raw_row_cap(db_session) == 77


SHUTDOWN_URL = "/settings/shutdown-confirmation"
SHUTDOWN_DEFAULT = {"mode": "intervals", "intervals": 4, "seconds": 60}


def test_shutdown_confirmation_requires_auth(test_client):
    assert test_client.get(SHUTDOWN_URL).status_code == 401
    assert test_client.put(SHUTDOWN_URL, json=SHUTDOWN_DEFAULT).status_code == 401


def test_shutdown_confirmation_rejects_regular_user_and_stores_nothing(test_client, db_session):
    headers = _auth_headers(db_session, test_client)

    assert test_client.get(SHUTDOWN_URL, headers=headers).status_code == 403
    response = test_client.put(SHUTDOWN_URL, json=SHUTDOWN_DEFAULT, headers=headers)

    assert response.status_code == 403
    assert db_session.get(AppSetting, SHUTDOWN_CONFIRMATION_KEY) is None


def test_shutdown_confirmation_defaults_to_four_intervals(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.get(SHUTDOWN_URL, headers=headers)

    assert response.status_code == 200
    assert response.json() == {**SHUTDOWN_DEFAULT, "updated_at": None, "updated_by": None}


def test_shutdown_confirmation_put_stores_it_and_records_who_and_when(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    payload = {"mode": "seconds", "intervals": 6, "seconds": 120.5}

    response = test_client.put(SHUTDOWN_URL, json=payload, headers=headers)

    body = response.json()
    assert response.status_code == 200
    assert {key: body[key] for key in payload} == payload
    assert body["updated_at"] is not None
    assert body["updated_by"] is not None
    assert test_client.get(SHUTDOWN_URL, headers=headers).json() == body
    assert get_shutdown_confirmation(db_session).mode == "seconds"


def test_shutdown_confirmation_put_overwrites_instead_of_adding_a_row(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    test_client.put(SHUTDOWN_URL, json={**SHUTDOWN_DEFAULT, "intervals": 5}, headers=headers)
    test_client.put(SHUTDOWN_URL, json={**SHUTDOWN_DEFAULT, "intervals": 7}, headers=headers)

    assert get_shutdown_confirmation(db_session).intervals == 7
    rows = db_session.scalars(
        select(AppSetting).where(AppSetting.key == SHUTDOWN_CONFIRMATION_KEY)
    ).all()
    assert len(rows) == 1


def test_shutdown_confirmation_rejects_invalid_values_and_keeps_the_stored_one(
    test_client, db_session
):
    headers = _superuser_headers(db_session, test_client)
    test_client.put(SHUTDOWN_URL, json={**SHUTDOWN_DEFAULT, "intervals": 5}, headers=headers)

    invalid_payloads = [
        {**SHUTDOWN_DEFAULT, "mode": "minutes"},
        {**SHUTDOWN_DEFAULT, "intervals": 0},
        {**SHUTDOWN_DEFAULT, "intervals": 21},
        {**SHUTDOWN_DEFAULT, "intervals": True},
        {**SHUTDOWN_DEFAULT, "intervals": 4.5},
        {**SHUTDOWN_DEFAULT, "seconds": 9},
        {**SHUTDOWN_DEFAULT, "seconds": 3601},
        {**SHUTDOWN_DEFAULT, "seconds": "60"},
        {**SHUTDOWN_DEFAULT, "extra": 1},
    ]
    for invalid in invalid_payloads:
        response = test_client.put(SHUTDOWN_URL, json=invalid, headers=headers)
        assert response.status_code == 422, invalid

    assert get_shutdown_confirmation(db_session).intervals == 5


def test_shutdown_confirmation_validation_error_does_not_echo_the_input(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.put(
        SHUTDOWN_URL, json={**SHUTDOWN_DEFAULT, "seconds": "secret-ish"}, headers=headers
    )

    assert response.status_code == 422
    assert "secret-ish" not in response.text


def test_corrupted_stored_shutdown_confirmation_falls_back_to_the_default(db_session):
    stored = {"mode": "seconds", "seconds": 1}
    db_session.add(AppSetting(key=SHUTDOWN_CONFIRMATION_KEY, value=stored))
    db_session.commit()

    assert get_shutdown_confirmation(db_session) == ShutdownConfirmation()


def test_non_object_stored_shutdown_confirmation_falls_back_to_the_default(db_session):
    db_session.add(AppSetting(key=SHUTDOWN_CONFIRMATION_KEY, value="seconds"))
    db_session.commit()

    assert get_shutdown_confirmation(db_session) == ShutdownConfirmation()
