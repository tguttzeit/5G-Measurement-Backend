"""Unit tests for app/routers/testing.py.

Device-key vs superuser-JWT auth boundaries for `POST /testing/results` already have
dedicated coverage in `tests/integration/test_api/test_testing_device_auth.py` against
a real Postgres. These tests instead isolate the business logic each endpoint adds on top of
that auth layer -- payload/auth device_id matching, invalid-device handling, filtering/
pagination bookkeeping, 404 boundaries, and the summary aggregation -- against a mocked
`Session`, per the issue's stated isolation approach.
"""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.auth import current_superuser
from app.db import get_db
from app.main import app
from app.models import Device
from app.models.testing import TestStatus as _TestStatus
from app.models.testing import TestType as _TestType
from app.routers.testing import verify_testing_submission_auth

client = TestClient(app)

FAKE_SUPERUSER = SimpleNamespace(
    id=1, email="admin", is_active=True, is_superuser=True, is_verified=True
)
FAKE_DEVICE = Device(device_id="probe-device-01", api_key_hash="irrelevant")


def _fake_result(
    result_id: int = 1,
    device_id: str = "probe-device-01",
    test_type: _TestType = _TestType.MODEM,
    status: _TestStatus = _TestStatus.PASSED,
    is_testing: bool = True,
    duration_ms: int | None = 100,
    error_message: str | None = None,
    details: dict | None = None,
) -> SimpleNamespace:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SimpleNamespace(
        id=result_id,
        device_id=device_id,
        test_type=test_type,
        status=status,
        executed_at=now,
        is_testing=is_testing,
        duration_ms=duration_ms,
        error_message=error_message,
        details=details,
        created_at=now,
    )


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# --- POST /testing/results --------------------------------------------------


def test_submit_requires_auth():
    response = client.post(
        "/testing/results",
        json={"device_id": "probe-device-01", "test_type": "modem", "status": "passed"},
    )

    assert response.status_code == 401


def test_submit_device_payload_mismatch_returns_403():
    app.dependency_overrides[verify_testing_submission_auth] = lambda: FAKE_DEVICE

    response = client.post(
        "/testing/results",
        json={"device_id": "some-other-device", "test_type": "modem", "status": "passed"},
    )

    assert response.status_code == 403


def test_submit_unregistered_device_id_returns_400():
    session = MagicMock()
    session.commit.side_effect = IntegrityError("insert", {}, Exception("fk violation"))

    app.dependency_overrides[verify_testing_submission_auth] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.post(
        "/testing/results",
        json={"device_id": "unregistered-device", "test_type": "modem", "status": "passed"},
    )

    assert response.status_code == 400
    session.rollback.assert_called_once()


def test_submit_success_as_superuser():
    session = MagicMock()

    def _refresh(obj):
        obj.id = 42

    session.refresh.side_effect = _refresh

    app.dependency_overrides[verify_testing_submission_auth] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.post(
        "/testing/results",
        json={"device_id": "probe-device-01", "test_type": "modem", "status": "passed"},
    )

    assert response.status_code == 201, response.text
    assert "42" in response.json()["message"]
    session.add.assert_called_once()
    session.commit.assert_called_once()


def test_submit_success_as_matching_device():
    session = MagicMock()
    session.refresh.side_effect = lambda obj: setattr(obj, "id", 7)

    app.dependency_overrides[verify_testing_submission_auth] = lambda: FAKE_DEVICE
    app.dependency_overrides[get_db] = lambda: session

    response = client.post(
        "/testing/results",
        json={"device_id": "probe-device-01", "test_type": "modem", "status": "passed"},
    )

    assert response.status_code == 201, response.text


def test_submit_invalid_test_type_rejected_with_422():
    """`test_type` is a Pydantic enum field, so an unknown value 422s before the handler runs."""
    app.dependency_overrides[verify_testing_submission_auth] = lambda: FAKE_SUPERUSER

    response = client.post(
        "/testing/results",
        json={"device_id": "probe-device-01", "test_type": "not-a-real-type", "status": "passed"},
    )

    assert response.status_code == 422


# --- GET /testing/results ----------------------------------------------------


def test_list_results_requires_auth():
    response = client.get("/testing/results")

    assert response.status_code == 401


def test_list_results_returns_mapped_results():
    session = MagicMock()
    session.scalar.return_value = 1
    session.scalars.return_value.all.return_value = [_fake_result(error_message="boom")]

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.get("/testing/results")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["results"][0]["device_id"] == "probe-device-01"
    assert body["results"][0]["test_type"] == "modem"
    assert body["results"][0]["status"] == "passed"
    assert body["results"][0]["error_message"] == "boom"


def test_list_results_page_size_over_limit_returns_422():
    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: MagicMock()

    response = client.get("/testing/results", params={"page_size": 5000})

    assert response.status_code == 422


# --- GET /testing/results/{id} -----------------------------------------------


def test_get_result_requires_auth():
    response = client.get("/testing/results/1")

    assert response.status_code == 401


def test_get_result_not_found_returns_404():
    session = MagicMock()
    session.get.return_value = None

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.get("/testing/results/999")

    assert response.status_code == 404


def test_get_result_wrong_is_testing_flag_returns_404():
    """A production row (is_testing=False) must not be returned via the default testing=True
    lookup."""
    session = MagicMock()
    session.get.return_value = _fake_result(is_testing=False)

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.get("/testing/results/1")

    assert response.status_code == 404


def test_get_result_success():
    session = MagicMock()
    session.get.return_value = _fake_result(error_message="boom")

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.get("/testing/results/1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["error_message"] == "boom"


# --- DELETE /testing/results/{id} --------------------------------------------


def test_delete_result_requires_auth():
    response = client.delete("/testing/results/1")

    assert response.status_code == 401


def test_delete_result_not_found_returns_404():
    session = MagicMock()
    session.get.return_value = None

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.delete("/testing/results/999")

    assert response.status_code == 404
    session.delete.assert_not_called()


def test_delete_result_success():
    session = MagicMock()
    session.get.return_value = _fake_result()

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.delete("/testing/results/1")

    assert response.status_code == 200
    session.delete.assert_called_once()
    session.commit.assert_called_once()


# --- DELETE /testing/results (bulk) -------------------------------------------


def test_delete_all_results_requires_auth():
    response = client.delete("/testing/results")

    assert response.status_code == 401


def test_delete_all_results_defaults_to_testing_data():
    session = MagicMock()
    session.execute.return_value.rowcount = 5

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.delete("/testing/results")

    assert response.status_code == 200, response.text
    assert "5" in response.json()["message"]
    session.execute.assert_called_once()
    session.commit.assert_called_once()


def test_delete_all_results_respects_is_testing_false():
    session = MagicMock()
    session.execute.return_value.rowcount = 2

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.delete("/testing/results", params={"is_testing": "false"})

    assert response.status_code == 200, response.text
    assert "2" in response.json()["message"]


def test_delete_all_results_reports_zero_deleted():
    session = MagicMock()
    session.execute.return_value.rowcount = 0

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.delete("/testing/results")

    assert response.status_code == 200, response.text
    assert "0" in response.json()["message"]


# --- GET /testing/summary -----------------------------------------------------


def test_summary_requires_auth():
    response = client.get("/testing/summary")

    assert response.status_code == 401


def test_summary_aggregates_counts():
    session = MagicMock()
    status_query = session.query.return_value.filter.return_value.group_by.return_value
    status_query.all.side_effect = [
        [(_TestStatus.PASSED, 3), (_TestStatus.FAILED, 1)],
        [(_TestType.MODEM, _TestStatus.PASSED, 3), (_TestType.MODEM, _TestStatus.FAILED, 1)],
    ]
    status_query.order_by.return_value.all.return_value = []
    session.scalars.return_value.all.return_value = []

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.get("/testing/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_tests"] == 4
    assert body["passed"] == 3
    assert body["failed"] == 1
    assert body["by_test_type"]["modem"]["passed"] == 3
    assert body["by_test_type"]["modem"]["failed"] == 1
    assert body["by_test_type"]["modem"]["total"] == 4
    assert body["failures_by_type_and_message"] == []


def test_summary_recent_executions_include_error_message():
    session = MagicMock()
    status_query = session.query.return_value.filter.return_value.group_by.return_value
    status_query.all.side_effect = [
        [(_TestStatus.FAILED, 1)],
        [(_TestType.GPS, _TestStatus.FAILED, 1)],
    ]
    status_query.order_by.return_value.all.return_value = []
    session.scalars.return_value.all.return_value = [
        _fake_result(test_type=_TestType.GPS, status=_TestStatus.FAILED, error_message="no gps fix")
    ]

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.get("/testing/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["recent_executions"][0]["error_message"] == "no gps fix"


def test_summary_failures_by_type_and_message_breakdown():
    session = MagicMock()
    status_query = session.query.return_value.filter.return_value.group_by.return_value
    status_query.all.side_effect = [
        [(_TestStatus.FAILED, 2)],
        [(_TestType.GPS, _TestStatus.FAILED, 2)],
    ]
    status_query.order_by.return_value.all.return_value = [
        (_TestType.GPS, "No GPS fix available (no valid GGA sentence received in time).", 1),
        (_TestType.COLLECTOR, "No GPS fix available to pair with a cell measurement.", 1),
    ]
    session.scalars.return_value.all.return_value = []

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_db] = lambda: session

    response = client.get("/testing/summary")

    assert response.status_code == 200
    body = response.json()
    breakdown = body["failures_by_type_and_message"]
    assert len(breakdown) == 2
    assert {
        "test_type": "gps",
        "error_message": "No GPS fix available (no valid GGA sentence received in time).",
        "count": 1,
    } in breakdown
    assert {
        "test_type": "collector",
        "error_message": "No GPS fix available to pair with a cell measurement.",
        "count": 1,
    } in breakdown
