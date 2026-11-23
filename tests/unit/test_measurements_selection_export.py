"""Request validation for `POST /measurements/export-selection` - rejected before
any database work, so no database is needed."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import get_settings
from app.main import app
from app.schemas.measurement import SelectionExportRequest

URL = "/measurements/export-selection"


def _post(body):
    return TestClient(app).post(URL, json=body)


def test_empty_id_list_is_rejected():
    assert _post({"ids": [], "format": "csv"}).status_code == 422


def test_oversized_id_list_is_rejected_without_echoing_ids():
    limit = get_settings().selection_export_max_ids

    response = _post({"ids": list(range(1, limit + 2)), "format": "csv"})

    assert response.status_code == 422
    assert "12345" not in response.text


@pytest.mark.parametrize("bad_id", [0, -1, "7", 1.5, True, None])
def test_ids_must_be_positive_integers(bad_id):
    assert _post({"ids": [1, bad_id], "format": "csv"}).status_code == 422


def test_format_is_a_closed_enum():
    assert _post({"ids": [1], "format": "png"}).status_code == 422
    assert _post({"ids": [1]}).status_code == 422


def test_unknown_fields_are_rejected():
    assert _post({"ids": [1], "format": "csv", "device_id": "x"}).status_code == 422


def test_ids_are_deduplicated_preserving_order():
    request = SelectionExportRequest(ids=[3, 1, 3, 2, 1], format="geojson")

    assert request.ids == [3, 1, 2]


def test_limit_applies_to_the_distinct_ids():
    limit = get_settings().selection_export_max_ids

    SelectionExportRequest(ids=[1] * (limit + 5), format="csv")
    with pytest.raises(ValidationError):
        SelectionExportRequest(ids=list(range(1, limit + 2)), format="csv")
