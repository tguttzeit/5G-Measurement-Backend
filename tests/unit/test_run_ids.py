"""Unit tests for run id helpers and the `run_id` field validation on the upload schemas."""
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.run_ids import LEGACY_RUN_ID_PREFIX, is_legacy_run_id, legacy_run_id
from app.schemas.datapoint import Datapoint
from app.schemas.latency import LatencyResult

FIX = {"position": {"latitude": 52.5, "longitude": 13.4}, "num_satellites": 8}


def _datapoint(**overrides) -> dict:
    return {
        "timestamp": "2026-07-30T12:00:00Z",
        "device_id": "dev-1",
        "mission_type": "ground",
        "fix": FIX,
        "cell_sample": {"rat": "LTE"},
        **overrides,
    }


def _latency_result(**overrides) -> dict:
    return {
        "test_type": "baseline",
        "flent_test": "ping",
        "device_id": "dev-1",
        "mission_type": "ground",
        "start_timestamp": "2026-07-30T12:00:00Z",
        "end_timestamp": "2026-07-30T12:01:00Z",
        "start_fix": FIX,
        "end_fix": FIX,
        **overrides,
    }


def test_legacy_run_id_combines_device_mission_type_and_utc_date():
    timestamp = datetime(2026, 7, 30, 23, 59, tzinfo=UTC)

    assert legacy_run_id("dev-1", "ground", timestamp) == "legacy-dev-1-ground-2026-07-30"


def test_legacy_run_id_uses_the_utc_date_not_the_local_one():
    late_evening_in_utc_minus_5 = datetime(2026, 7, 30, 22, 0, tzinfo=timezone(timedelta(hours=-5)))

    assert legacy_run_id("dev-1", "ground", late_evening_in_utc_minus_5).endswith("2026-07-31")


def test_legacy_run_id_treats_naive_timestamps_as_utc():
    assert legacy_run_id("dev-1", "ground", datetime(2026, 7, 30, 1, 0)).endswith("2026-07-30")


def test_is_legacy_run_id_recognizes_only_the_synthetic_prefix():
    assert is_legacy_run_id(f"{LEGACY_RUN_ID_PREFIX}dev-1-ground-2026-07-30")
    assert not is_legacy_run_id("7f9c2c1e-0f4b-4d6c-9a58-3b5e2f0c9d11")


def test_datapoint_run_id_is_optional():
    assert Datapoint.model_validate(_datapoint()).run_id is None


@pytest.mark.parametrize("run_id", ["7f9c2c1e-0f4b-4d6c-9a58-3b5e2f0c9d11", "run_1.a-B", "x" * 64])
def test_datapoint_accepts_valid_run_ids(run_id):
    assert Datapoint.model_validate(_datapoint(run_id=run_id)).run_id == run_id


@pytest.mark.parametrize(
    "run_id",
    ["", "x" * 65, "has space", "semi;colon", "quote'", "new\nline", "<script>", "legacy-dev-1"],
)
def test_datapoint_rejects_invalid_run_ids(run_id):
    with pytest.raises(ValidationError):
        Datapoint.model_validate(_datapoint(run_id=run_id))


def test_latency_result_run_id_is_optional_and_validated():
    assert LatencyResult.model_validate(_latency_result()).run_id is None
    assert LatencyResult.model_validate(_latency_result(run_id="run-1")).run_id == "run-1"
    with pytest.raises(ValidationError):
        LatencyResult.model_validate(_latency_result(run_id="bad id"))
