"""Unit tests for ConfigOverrideCreate's allow-list.

`test_interval_s` never mapped to a real device concept (cadences are per-feature) and is
dropped entirely. The nine per-feature cadence/bounds fields it's replaced by, plus
`day_end_threshold_s` (kept staged as a no-op), are exercised here
since `extra="forbid"` makes this schema the allow-list itself - a typo or dropped field here
silently changes what a superuser can remotely reach.
"""
import pytest
from pydantic import ValidationError

from app.schemas.commands import ConfigOverrideCreate

FLOAT_FIELDS = [
    "movement_gate_poll_interval_s",
    "latency_test_baseline_interval_s",
    "latency_test_load_interval_s",
    "latency_test_poll_interval_s",
    "heartbeat_interval_s",
    "collector_max_wait_for_first_fix",
    "movement_gate_movement_threshold",
]


def test_test_interval_s_is_no_longer_a_valid_field():
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(test_interval_s=300)


def test_day_end_threshold_s_still_accepted():
    override = ConfigOverrideCreate(day_end_threshold_s=3600)

    assert override.day_end_threshold_s == 3600


@pytest.mark.parametrize("field", FLOAT_FIELDS)
def test_new_float_field_accepts_a_value(field):
    override = ConfigOverrideCreate(**{field: 12.5})

    assert getattr(override, field) == 12.5


def test_movement_gate_confirmations_required_accepts_an_int():
    override = ConfigOverrideCreate(movement_gate_confirmations_required=3)

    assert override.movement_gate_confirmations_required == 3


def test_run_status_empty_captures_threshold_is_an_int():
    override = ConfigOverrideCreate(run_status_empty_captures_until_pipeline_broken=5)

    assert override.run_status_empty_captures_until_pipeline_broken == 5
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(run_status_empty_captures_until_pipeline_broken=5.5)


def test_unknown_field_still_rejected():
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(upload_host="evil.example.com")


def test_empty_override_is_valid():
    override = ConfigOverrideCreate()

    assert override.model_dump(exclude_unset=True) == {}
