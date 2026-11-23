"""Tests for GET /config-schema that need no database.

The 403 case needs a real non-superuser row and lives in
tests/integration/test_api/test_config_schema.py.
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import current_superuser
from app.config_override_spec import CONFIG_OVERRIDE_SPEC, GROUP_ORDER
from app.main import app

URL = "/config-schema"


@pytest.fixture
def anonymous_client():
    return TestClient(app)


@pytest.fixture
def superuser_client():
    app.dependency_overrides[current_superuser] = lambda: object()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(current_superuser, None)


def test_anonymous_request_is_rejected_with_401(anonymous_client):
    assert anonymous_client.get(URL).status_code == 401


def test_groups_are_returned_in_display_order(superuser_client):
    body = superuser_client.get(URL).json()

    assert [group["id"] for group in body["groups"]] == list(GROUP_ORDER)


def test_every_registry_field_is_returned_exactly_once(superuser_client):
    body = superuser_client.get(URL).json()

    keys = [field["key"] for group in body["groups"] for field in group["fields"]]
    assert sorted(keys) == sorted(spec.key for spec in CONFIG_OVERRIDE_SPEC)


def _field(body, key):
    return next(f for g in body["groups"] for f in g["fields"] if f["key"] == key)


def test_float_field_describes_type_range_unit_and_flags(superuser_client):
    field = _field(superuser_client.get(URL).json(), "collector_position_threshold")

    assert field == {
        "key": "collector_position_threshold",
        "type": "float",
        "min": 0.1,
        "max": 1000,
        "values": None,
        "nullable": False,
        "unit": "m",
        "requires_confirmation": False,
        "no_effect_yet": False,
    }


def test_enum_field_lists_its_values_and_has_no_range(superuser_client):
    field = _field(superuser_client.get(URL).json(), "modem_mode")

    assert (field["type"], field["values"], field["min"], field["max"]) == (
        "enum",
        ["serving_cell", "sa_scan"],
        None,
        None,
    )
    assert field["requires_confirmation"] is True


def test_nullable_and_no_effect_flags_are_exposed(superuser_client):
    body = superuser_client.get(URL).json()

    assert _field(body, "movement_gate_home_latitude")["nullable"] is True
    assert _field(body, "day_end_threshold_s")["no_effect_yet"] is True


def test_system_mode_is_not_part_of_the_schema(superuser_client):
    keys = {f["key"] for g in superuser_client.get(URL).json()["groups"] for f in g["fields"]}

    assert "system_mode" not in keys


def test_int_field_bounds_are_returned_as_integers(superuser_client):
    field = _field(superuser_client.get(URL).json(), "gnss_receiver_retries")

    assert (field["min"], field["max"]) == (0, 20)
    assert isinstance(field["min"], int) and isinstance(field["max"], int)


def test_idle_threshold_advertises_zero_as_its_minimum(superuser_client):
    field = _field(superuser_client.get(URL).json(), "idle_threshold_s")

    assert (field["min"], field["max"]) == (0, 86400)
