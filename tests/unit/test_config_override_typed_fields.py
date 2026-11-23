"""Unit tests for the typed remote config overrides.
`ConfigOverrideCreate` is the backend's validation layer for what the device re-validates
itself, so every bound here is the same bound the device applies.
"""
import math

import pytest
from pydantic import ValidationError

from app.schemas.commands import ConfigOverrideCreate

ENUM_FIELDS = {
    "collector_capture_gate": ("distance", "time"),
    "device_mission_type": ("ground", "drone"),
    "modem_mode": ("serving_cell", "sa_scan"),
}

BOOL_FIELDS = [
    "collector_gps_enabled",
    "latency_test_enabled",
    "display_enabled",
    "system_running_on_pi",
]

# field: (low, high, is_int)
RANGED_FIELDS = {
    "collector_position_threshold": (0.1, 1000, False),
    "collector_capture_interval_s": (1, 86400, False),
    "collector_wait_log_interval": (1, 3600, False),
    "collector_gps_disabled_poll_interval_s": (1, 86400, False),
    "movement_gate_home_latitude": (-90, 90, False),
    "movement_gate_home_longitude": (-180, 180, False),
    "movement_gate_home_departure_threshold": (1, 10000, False),
    "display_refresh_interval_s": (0.5, 3600, False),
    "modem_sim_unlock_poll_attempts": (1, 100, True),
    "modem_sim_unlock_poll_interval": (0.1, 60, False),
    "gnss_receiver_retries": (0, 20, True),
    "gnss_receiver_retry_delay_s": (0, 60, False),
}

NULLABLE_FIELDS = ["movement_gate_home_latitude", "movement_gate_home_longitude"]
NON_NULLABLE_FIELDS = (
    list(ENUM_FIELDS)
    + BOOL_FIELDS
    + [f for f in RANGED_FIELDS if f not in NULLABLE_FIELDS]
    + ["heartbeat_interval_s", "idle_threshold_s"]
)

REMOVED_FIELDS = ["rsrp_threshold", "rsrq_threshold", "sinr_threshold", "system_shutdown_gpio"]


def _lo_hi(field):
    low, high, is_int = RANGED_FIELDS[field]
    return (int(low), int(high)) if is_int else (float(low), float(high))


@pytest.mark.parametrize("field,values", ENUM_FIELDS.items())
def test_enum_field_accepts_every_member(field, values):
    for value in values:
        assert getattr(ConfigOverrideCreate(**{field: value}), field) == value


@pytest.mark.parametrize("field", ENUM_FIELDS)
@pytest.mark.parametrize("value", ["", "Time", " time", "auto", 1, True, ["time"]])
def test_enum_field_rejects_anything_outside_the_set(field, value):
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(**{field: value})


@pytest.mark.parametrize("field", BOOL_FIELDS)
def test_bool_field_accepts_true_and_false(field):
    assert getattr(ConfigOverrideCreate(**{field: False}), field) is False
    assert getattr(ConfigOverrideCreate(**{field: True}), field) is True


@pytest.mark.parametrize("field", BOOL_FIELDS)
@pytest.mark.parametrize("value", [1, 0, "true", "false", "yes"])
def test_bool_field_rejects_non_bool(field, value):
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(**{field: value})


@pytest.mark.parametrize("field", RANGED_FIELDS)
def test_ranged_field_accepts_both_bounds(field):
    low, high = _lo_hi(field)

    assert getattr(ConfigOverrideCreate(**{field: low}), field) == low
    assert getattr(ConfigOverrideCreate(**{field: high}), field) == high


@pytest.mark.parametrize("field", RANGED_FIELDS)
def test_ranged_field_rejects_just_outside_either_bound(field):
    low, high = _lo_hi(field)
    step = 1 if isinstance(low, int) else 0.01

    for value in (low - step, high + step):
        with pytest.raises(ValidationError):
            ConfigOverrideCreate(**{field: value})


@pytest.mark.parametrize("field", RANGED_FIELDS)
@pytest.mark.parametrize("value", ["5", True, False, [5], {"v": 5}])
def test_ranged_field_rejects_non_numbers_and_bools(field, value):
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(**{field: value})


@pytest.mark.parametrize("field", RANGED_FIELDS)
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_ranged_field_rejects_nan_and_infinity(field, value):
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(**{field: value})


@pytest.mark.parametrize(
    "field", [f for f, (_, _, is_int) in RANGED_FIELDS.items() if is_int]
)
def test_int_field_rejects_fractional_numbers(field):
    low, _ = _lo_hi(field)

    with pytest.raises(ValidationError):
        ConfigOverrideCreate(**{field: low + 0.5})


@pytest.mark.parametrize("field", NULLABLE_FIELDS)
def test_nullable_field_accepts_an_explicit_null_distinct_from_not_sent(field):
    sent_null = ConfigOverrideCreate(**{field: None})

    assert sent_null.model_dump(exclude_unset=True) == {field: None}
    assert ConfigOverrideCreate().model_dump(exclude_unset=True) == {}


@pytest.mark.parametrize("field", NON_NULLABLE_FIELDS)
def test_non_nullable_field_rejects_an_explicit_null(field):
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(**{field: None})


@pytest.mark.parametrize("field", REMOVED_FIELDS + ["system_mode", "mode", "hmac_secret"])
def test_removed_and_non_queueable_fields_are_rejected(field):
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(**{field: 1 if field.endswith("threshold") else "auto"})


def test_validation_errors_do_not_echo_the_submitted_value():
    with pytest.raises(ValidationError) as excinfo:
        ConfigOverrideCreate(gnss_receiver_retries=999)

    error = excinfo.value.errors(include_input=False)[0]
    assert error["loc"] == ("gnss_receiver_retries",)
    assert "999" not in error["msg"]
