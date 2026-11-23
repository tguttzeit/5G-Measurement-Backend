"""Unit tests for the config override field registry.

The registry is the single definition of what can be overridden; `ConfigOverrideCreate`
validation and `GET /config-schema` are derived from it. These tests pin the registry content to
the device contract and guard against the model and the registry drifting apart.
"""
import math

import pytest
from pydantic import ValidationError

from app.config_override_spec import (
    CONFIG_OVERRIDE_SPEC,
    GROUP_ORDER,
    FieldKind,
    specs_in_display_order,
)
from app.schemas.commands import ConfigOverrideCreate

SPEC_BY_KEY = {spec.key: spec for spec in CONFIG_OVERRIDE_SPEC}

EXPECTED_KEYS_BY_GROUP = {
    "measurement_cycle": [
        "collector_capture_gate",
        "collector_position_threshold",
        "collector_capture_interval_s",
        "idle_threshold_s",
        "collector_max_wait_for_first_fix",
        "collector_wait_log_interval",
        "collector_gps_enabled",
        "collector_gps_disabled_poll_interval_s",
    ],
    "movement_detection": [
        "movement_gate_poll_interval_s",
        "movement_gate_movement_threshold",
        "movement_gate_confirmations_required",
        "movement_gate_home_latitude",
        "movement_gate_home_longitude",
        "movement_gate_home_departure_threshold",
    ],
    "latency_tests": [
        "latency_test_enabled",
        "latency_test_baseline_interval_s",
        "latency_test_load_interval_s",
        "latency_test_poll_interval_s",
    ],
    "backend_operation": [
        "heartbeat_interval_s",
        "device_mission_type",
        "display_enabled",
        "display_refresh_interval_s",
        "day_end_threshold_s",
    ],
    "pipeline_monitoring": ["run_status_empty_captures_until_pipeline_broken"],
    "risky": [
        "modem_mode",
        "modem_sim_unlock_poll_attempts",
        "modem_sim_unlock_poll_interval",
        "gnss_receiver_retries",
        "gnss_receiver_retry_delay_s",
        "system_running_on_pi",
    ],
}


def _bounds(spec):
    return (int(spec.minimum), int(spec.maximum)) if spec.kind is FieldKind.INT else (
        float(spec.minimum),
        float(spec.maximum),
    )


def _ranged(kind):
    return [spec for spec in CONFIG_OVERRIDE_SPEC if spec.kind is kind]

NUMERIC_SPECS = _ranged(FieldKind.FLOAT) + _ranged(FieldKind.INT)


def test_groups_and_fields_are_in_the_documented_display_order():
    assert list(GROUP_ORDER) == list(EXPECTED_KEYS_BY_GROUP)
    for group, keys in EXPECTED_KEYS_BY_GROUP.items():
        assert [s.key for s in specs_in_display_order() if s.group == group] == keys


def test_registry_has_no_duplicate_keys():
    assert len(SPEC_BY_KEY) == len(CONFIG_OVERRIDE_SPEC)


@pytest.mark.parametrize(
    "key", ["system_mode", "rsrp_threshold", "rsrq_threshold", "sinr_threshold"]
)
def test_registry_excludes_system_mode_and_removed_thresholds(key):
    assert key not in SPEC_BY_KEY


def test_exactly_the_seven_risky_fields_require_confirmation():
    assert {s.key for s in CONFIG_OVERRIDE_SPEC if s.requires_confirmation} == set(
        EXPECTED_KEYS_BY_GROUP["risky"]
    )


def test_only_day_end_threshold_has_no_effect_yet():
    assert [s.key for s in CONFIG_OVERRIDE_SPEC if s.no_effect_yet] == ["day_end_threshold_s"]


def test_only_the_home_position_is_nullable():
    assert {s.key for s in CONFIG_OVERRIDE_SPEC if s.nullable} == {
        "movement_gate_home_latitude",
        "movement_gate_home_longitude",
    }


@pytest.mark.parametrize(
    "key,kind,minimum,maximum",
    [
        ("idle_threshold_s", FieldKind.FLOAT, 0, 86400),
        ("collector_max_wait_for_first_fix", FieldKind.FLOAT, 1, 3600),
        ("movement_gate_poll_interval_s", FieldKind.FLOAT, 1, 86400),
        ("movement_gate_movement_threshold", FieldKind.FLOAT, 0.1, 1000),
        ("movement_gate_confirmations_required", FieldKind.INT, 1, 10),
        ("latency_test_baseline_interval_s", FieldKind.FLOAT, 1, 86400),
        ("latency_test_load_interval_s", FieldKind.FLOAT, 1, 86400),
        ("latency_test_poll_interval_s", FieldKind.FLOAT, 1, 86400),
        ("heartbeat_interval_s", FieldKind.FLOAT, 1, 86400),
        ("day_end_threshold_s", FieldKind.FLOAT, 0, 86400),
        ("run_status_empty_captures_until_pipeline_broken", FieldKind.INT, 1, 100),
    ],
)
def test_previously_unbounded_fields_now_have_the_contract_type_and_range(
    key, kind, minimum, maximum
):
    spec = SPEC_BY_KEY[key]

    assert (spec.kind, spec.minimum, spec.maximum) == (kind, minimum, maximum)


def test_distance_fields_carry_a_metre_unit_and_interval_fields_a_seconds_unit():
    assert SPEC_BY_KEY["collector_position_threshold"].unit == "m"
    assert SPEC_BY_KEY["movement_gate_movement_threshold"].unit == "m"
    assert SPEC_BY_KEY["movement_gate_home_departure_threshold"].unit == "m"
    assert SPEC_BY_KEY["heartbeat_interval_s"].unit == "s"
    assert SPEC_BY_KEY["collector_gps_enabled"].unit is None


def test_enum_specs_list_exactly_the_device_accepted_values():
    assert SPEC_BY_KEY["collector_capture_gate"].choices == ("distance", "time")
    assert SPEC_BY_KEY["device_mission_type"].choices == ("ground", "drone")
    assert SPEC_BY_KEY["modem_mode"].choices == ("serving_cell", "sa_scan")


# --- consistency between the registry and the derived model --------------------------------


def test_model_fields_are_exactly_the_registry_keys():
    assert set(ConfigOverrideCreate.model_fields) == set(SPEC_BY_KEY)


@pytest.mark.parametrize("spec", NUMERIC_SPECS, ids=lambda s: s.key)
def test_model_accepts_both_bounds_and_rejects_just_outside(spec):
    low, high = _bounds(spec)
    step = 1 if spec.kind is FieldKind.INT else 0.01

    for inside in (low, high):
        assert getattr(ConfigOverrideCreate(**{spec.key: inside}), spec.key) == inside
    for outside in (low - step, high + step):
        with pytest.raises(ValidationError):
            ConfigOverrideCreate(**{spec.key: outside})


@pytest.mark.parametrize("spec", NUMERIC_SPECS, ids=lambda s: s.key)
@pytest.mark.parametrize("value", ["5", True, False, math.nan, math.inf, -math.inf])
def test_model_rejects_non_numbers_bools_nan_and_infinity(spec, value):
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(**{spec.key: value})


@pytest.mark.parametrize("spec", _ranged(FieldKind.INT), ids=lambda s: s.key)
def test_model_rejects_fractions_for_int_fields(spec):
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(**{spec.key: spec.minimum + 0.5})


@pytest.mark.parametrize("spec", _ranged(FieldKind.ENUM), ids=lambda s: s.key)
def test_model_accepts_exactly_the_registry_enum_values(spec):
    for choice in spec.choices:
        assert getattr(ConfigOverrideCreate(**{spec.key: choice}), spec.key) == choice
    for other in ("", "Time", "auto", 1, True):
        with pytest.raises(ValidationError):
            ConfigOverrideCreate(**{spec.key: other})


@pytest.mark.parametrize("spec", _ranged(FieldKind.BOOL), ids=lambda s: s.key)
def test_model_accepts_only_real_booleans(spec):
    assert getattr(ConfigOverrideCreate(**{spec.key: True}), spec.key) is True
    for other in (1, 0, "true"):
        with pytest.raises(ValidationError):
            ConfigOverrideCreate(**{spec.key: other})


@pytest.mark.parametrize("spec", CONFIG_OVERRIDE_SPEC, ids=lambda s: s.key)
def test_model_nullability_matches_the_registry(spec):
    if spec.nullable:
        assert ConfigOverrideCreate(**{spec.key: None}).model_dump(exclude_unset=True) == {
            spec.key: None
        }
    else:
        with pytest.raises(ValidationError):
            ConfigOverrideCreate(**{spec.key: None})


def test_idle_threshold_accepts_zero_to_disable_the_idle_end():
    assert ConfigOverrideCreate(idle_threshold_s=0).idle_threshold_s == 0


@pytest.mark.parametrize("value", [-0.01, -1, math.nan, math.inf, -math.inf])
def test_idle_threshold_still_rejects_negative_nan_and_infinity(value):
    with pytest.raises(ValidationError):
        ConfigOverrideCreate(idle_threshold_s=value)
