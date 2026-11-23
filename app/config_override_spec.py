"""Single definition of the remotely overridable device config fields.

`ConfigOverrideCreate` (validation) and `GET /config-schema` (form metadata) are both derived
from `CONFIG_OVERRIDE_SPEC`, so a field's type, bounds and flags cannot differ between what the
queue endpoint accepts and what the Remote Configuration form offers. The bounds mirror the
device's own validation; new fields or enum values need a change on both sides.

`system_mode` is deliberately absent: it is only reported in `current_config`.
Descriptions and translations belong to the frontend and are not part of the registry.
"""
from dataclasses import dataclass
from enum import StrEnum


class FieldKind(StrEnum):
    FLOAT = "float"
    INT = "int"
    ENUM = "enum"
    BOOL = "bool"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: FieldKind
    group: str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None
    nullable: bool = False
    unit: str | None = None
    requires_confirmation: bool = False
    no_effect_yet: bool = False


GROUP_ORDER = (
    "measurement_cycle",
    "movement_detection",
    "latency_tests",
    "backend_operation",
    "pipeline_monitoring",
    "risky",
)


def _float(key, group, minimum, maximum, **options) -> FieldSpec:
    return FieldSpec(key, FieldKind.FLOAT, group, minimum, maximum, **options)


def _int(key, group, minimum, maximum, **options) -> FieldSpec:
    return FieldSpec(key, FieldKind.INT, group, minimum, maximum, **options)


def _enum(key, group, *choices, **options) -> FieldSpec:
    return FieldSpec(key, FieldKind.ENUM, group, choices=choices, **options)


def _bool(key, group, **options) -> FieldSpec:
    return FieldSpec(key, FieldKind.BOOL, group, **options)


def _seconds_float(key, group, minimum, maximum, **options) -> FieldSpec:
    return _float(key, group, minimum, maximum, unit="s", **options)


def _risky(build, key, *args) -> FieldSpec:
    """Wrong values here can make a device unusable until someone is physically on site."""
    return build(key, "risky", *args, requires_confirmation=True)


CONFIG_OVERRIDE_SPEC: tuple[FieldSpec, ...] = (
    _enum("collector_capture_gate", "measurement_cycle", "distance", "time"),
    _float("collector_position_threshold", "measurement_cycle", 0.1, 1000, unit="m"),
    _seconds_float("collector_capture_interval_s", "measurement_cycle", 1, 86400),
    _seconds_float("idle_threshold_s", "measurement_cycle", 0, 86400),
    _float("collector_max_wait_for_first_fix", "measurement_cycle", 1, 3600),
    _float("collector_wait_log_interval", "measurement_cycle", 1, 3600),
    _bool("collector_gps_enabled", "measurement_cycle"),
    _seconds_float("collector_gps_disabled_poll_interval_s", "measurement_cycle", 1, 86400),
    _seconds_float("movement_gate_poll_interval_s", "movement_detection", 1, 86400),
    _float("movement_gate_movement_threshold", "movement_detection", 0.1, 1000, unit="m"),
    _int("movement_gate_confirmations_required", "movement_detection", 1, 10),
    _float("movement_gate_home_latitude", "movement_detection", -90, 90, nullable=True),
    _float("movement_gate_home_longitude", "movement_detection", -180, 180, nullable=True),
    _float(
        "movement_gate_home_departure_threshold", "movement_detection", 1, 10000, unit="m"
    ),
    _bool("latency_test_enabled", "latency_tests"),
    _seconds_float("latency_test_baseline_interval_s", "latency_tests", 1, 86400),
    _seconds_float("latency_test_load_interval_s", "latency_tests", 1, 86400),
    _seconds_float("latency_test_poll_interval_s", "latency_tests", 1, 86400),
    _seconds_float("heartbeat_interval_s", "backend_operation", 1, 86400),
    _enum("device_mission_type", "backend_operation", "ground", "drone"),
    _bool("display_enabled", "backend_operation"),
    _seconds_float("display_refresh_interval_s", "backend_operation", 0.5, 3600),
    _seconds_float("day_end_threshold_s", "backend_operation", 0, 86400, no_effect_yet=True),
    _int(
        "run_status_empty_captures_until_pipeline_broken", "pipeline_monitoring", 1, 100
    ),
    _risky(_enum, "modem_mode", "serving_cell", "sa_scan"),
    _risky(_int, "modem_sim_unlock_poll_attempts", 1, 100),
    _risky(_float, "modem_sim_unlock_poll_interval", 0.1, 60),
    _risky(_int, "gnss_receiver_retries", 0, 20),
    _risky(_seconds_float, "gnss_receiver_retry_delay_s", 0, 60),
    _risky(_bool, "system_running_on_pi"),
)


def specs_in_display_order() -> list[FieldSpec]:
    return sorted(CONFIG_OVERRIDE_SPEC, key=lambda spec: GROUP_ORDER.index(spec.group))
