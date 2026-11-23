"""Tests for /favorite-config-fields that need no database.

The behavior against real rows lives in tests/integration/test_api/test_favorite_config_fields.py.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

URL = "/favorite-config-fields"


@pytest.fixture
def anonymous_client():
    return TestClient(app)


def test_anonymous_get_is_rejected_with_401(anonymous_client):
    assert anonymous_client.get(URL).status_code == 401


def test_anonymous_put_is_rejected_with_401(anonymous_client):
    assert anonymous_client.put(URL, json={"field_keys": []}).status_code == 401
