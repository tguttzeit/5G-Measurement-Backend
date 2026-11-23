"""Integration tests for GET /config-schema: the superuser boundary against real
user rows, and parity between the metadata and what the queue endpoint accepts.
"""
import pytest

from app.config_override_spec import CONFIG_OVERRIDE_SPEC
from app.models.user import User
from tests.integration.test_api.test_commands import (
    CONFIG_OVERRIDE_URL,
    KNOWN_DEVICE_ID,
    _login,
    _register_device,
    _superuser_headers,
    password_helper,
)

URL = "/config-schema"


def test_anonymous_request_gets_401(test_client, db_session):
    assert test_client.get(URL).status_code == 401


def test_non_superuser_gets_403(test_client, db_session):
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

    response = test_client.get(URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_superuser_gets_the_registry(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.get(URL, headers=headers)

    assert response.status_code == 200
    keys = [f["key"] for g in response.json()["groups"] for f in g["fields"]]
    assert sorted(keys) == sorted(spec.key for spec in CONFIG_OVERRIDE_SPEC)


@pytest.mark.parametrize("spec", CONFIG_OVERRIDE_SPEC, ids=lambda s: s.key)
def test_queue_endpoint_accepts_the_upper_bound_the_schema_advertises(
    test_client, db_session, spec
):
    headers = _superuser_headers(db_session, test_client)
    _register_device(db_session)
    schema = test_client.get(URL, headers=headers).json()
    advertised = next(
        f for g in schema["groups"] for f in g["fields"] if f["key"] == spec.key
    )
    value = {
        "float": advertised["max"],
        "int": advertised["max"],
        "enum": (advertised["values"] or [None])[0],
        "bool": True,
    }[advertised["type"]]

    response = test_client.post(
        CONFIG_OVERRIDE_URL.format(device_id=KNOWN_DEVICE_ID),
        json={spec.key: value},
        headers=headers,
    )

    assert response.status_code == 200, response.text
