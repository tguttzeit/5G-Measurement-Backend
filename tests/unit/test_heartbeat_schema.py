"""Unit tests for HeartbeatPayload's derived properties.

`app/routers/heartbeat.py` reads these properties (not the raw `since_run_start`/`storage`
dicts) when building the stored `Heartbeat` row, so a wrong default here would silently
corrupt ingested data rather than raising anywhere.
"""
import pytest
from pydantic import ValidationError

from app.schemas.heartbeat import GpsFixStatus, HeartbeatPayload, RunPhase

FULL_PAYLOAD = {
    "since_run_start": {"datapoints_total": 100, "good": 80, "bad": 15, "invalid": 5},
    "pipeline_broken": False,
    "storage": {"pending_files": 3, "disk_free_bytes": 50_000_000_000},
}


def test_all_fields_read_from_full_payload():
    payload = HeartbeatPayload.model_validate(FULL_PAYLOAD)

    assert payload.datapoints_total == 100
    assert payload.datapoints_valid == 95
    assert payload.datapoints_invalid == 5
    assert payload.storage_pending_files == 3
    assert payload.storage_disk_free_bytes == 50_000_000_000


def test_missing_since_run_start_keys_default_to_zero():
    payload = HeartbeatPayload.model_validate(
        {"since_run_start": {}, "pipeline_broken": False, "storage": {}}
    )

    assert payload.datapoints_total == 0
    assert payload.datapoints_valid == 0
    assert payload.datapoints_invalid == 0
    assert payload.storage_pending_files == 0
    assert payload.storage_disk_free_bytes == 0


def test_partial_since_run_start_only_defaults_missing_keys():
    payload = HeartbeatPayload.model_validate(
        {
            "since_run_start": {"datapoints_total": 42},
            "pipeline_broken": True,
            "storage": {"pending_files": 7},
        }
    )

    assert payload.datapoints_total == 42
    assert payload.datapoints_valid == 0
    assert payload.storage_pending_files == 7
    assert payload.storage_disk_free_bytes == 0


def test_pipeline_broken_is_passed_through():
    payload = HeartbeatPayload.model_validate(FULL_PAYLOAD)

    assert payload.pipeline_broken is False

    broken_payload = HeartbeatPayload.model_validate({**FULL_PAYLOAD, "pipeline_broken": True})

    assert broken_payload.pipeline_broken is True


def test_current_config_defaults_to_none_when_omitted():
    payload = HeartbeatPayload.model_validate(FULL_PAYLOAD)

    assert payload.current_config is None


def test_current_config_is_passed_through_when_present():
    payload = HeartbeatPayload.model_validate(
        {**FULL_PAYLOAD, "current_config": {"rsrp_threshold": -100.0, "heartbeat_interval_s": 60.0}}
    )

    assert payload.current_config == {"rsrp_threshold": -100.0, "heartbeat_interval_s": 60.0}


# --- run_phase / gps_fix ---------------------------------------------


def test_run_phase_and_gps_fix_default_to_none_when_omitted():
    payload = HeartbeatPayload.model_validate(FULL_PAYLOAD)

    assert payload.run_phase is None
    assert payload.gps_fix is None


@pytest.mark.parametrize(
    "phase",
    [
        "recovering_pending_data",
        "waiting_for_gps_fix",
        "waiting_for_movement",
        "manual_mode_idle",
        "recovery_idle",
        "starting_up",
        "stopping",
        "active_measuring",
        "finalizing",
        "done",
        "shutting_down",
        "rebooting",
        "critical_error",
    ],
)
def test_run_phase_accepts_every_documented_value(phase):
    payload = HeartbeatPayload.model_validate({**FULL_PAYLOAD, "run_phase": phase})

    assert payload.run_phase == RunPhase(phase)


def test_run_phase_rejects_the_legacy_waiting_mode_idle():
    with pytest.raises(ValidationError):
        HeartbeatPayload.model_validate({**FULL_PAYLOAD, "run_phase": "waiting_mode_idle"})


def test_run_phase_rejects_value_outside_the_fixed_enum():
    with pytest.raises(ValidationError):
        HeartbeatPayload.model_validate({**FULL_PAYLOAD, "run_phase": "doing_something_else"})


def test_gps_fix_is_passed_through_when_present():
    payload = HeartbeatPayload.model_validate(
        {
            **FULL_PAYLOAD,
            "gps_fix": {"has_fix": True, "num_satellites": 8, "fix_age_s": 1.5},
        }
    )

    assert payload.gps_fix == GpsFixStatus(has_fix=True, num_satellites=8, fix_age_s=1.5)


def test_gps_fix_allows_null_num_satellites_and_fix_age():
    payload = HeartbeatPayload.model_validate(
        {
            **FULL_PAYLOAD,
            "gps_fix": {"has_fix": False, "num_satellites": None, "fix_age_s": None},
        }
    )

    assert payload.gps_fix.num_satellites is None
    assert payload.gps_fix.fix_age_s is None


def test_gps_fix_rejects_negative_num_satellites():
    with pytest.raises(ValidationError):
        HeartbeatPayload.model_validate(
            {**FULL_PAYLOAD, "gps_fix": {"has_fix": True, "num_satellites": -1}}
        )


def test_gps_fix_rejects_num_satellites_above_upper_bound():
    with pytest.raises(ValidationError):
        HeartbeatPayload.model_validate(
            {**FULL_PAYLOAD, "gps_fix": {"has_fix": True, "num_satellites": 65}}
        )


def test_gps_fix_rejects_negative_fix_age():
    with pytest.raises(ValidationError):
        HeartbeatPayload.model_validate(
            {**FULL_PAYLOAD, "gps_fix": {"has_fix": True, "fix_age_s": -0.1}}
        )


# --- valid / invalid sample quality ---------------------------


def _payload(since_run_start: dict, **extra) -> HeartbeatPayload:
    return HeartbeatPayload.model_validate(
        {"since_run_start": since_run_start, "pipeline_broken": False, "storage": {}, **extra}
    )


def test_new_device_valid_count_is_read_directly():
    payload = _payload({"datapoints_total": 142, "valid": 138, "invalid": 4})

    assert payload.datapoints_valid == 138
    assert payload.datapoints_invalid == 4


def test_old_device_good_and_bad_are_summed_into_valid():
    payload = _payload({"datapoints_total": 100, "good": 80, "bad": 15, "invalid": 5})

    assert payload.datapoints_valid == 95


def test_valid_wins_over_good_and_bad_when_both_shapes_are_present():
    payload = _payload({"valid": 7, "good": 80, "bad": 15, "invalid": 0})

    assert payload.datapoints_valid == 7


# --- nonce ---------------------------------------------------------------------


def test_nonce_is_optional():
    assert _payload({}).nonce is None


@pytest.mark.parametrize("nonce", ["9f3c1a7e5b2d4c88a1e06f3b7d92c4aa", "a", "A1" * 32])
def test_nonce_accepts_one_to_sixty_four_alphanumerics(nonce):
    assert _payload({}, nonce=nonce).nonce == nonce


@pytest.mark.parametrize(
    "nonce", ["", "a" * 65, "abc def", "abc-def", 'a"b', "a\\b", "abc\n", "nön", 123, None]
)
def test_nonce_rejects_other_lengths_charsets_and_types(nonce):
    if nonce is None:
        assert _payload({}, nonce=nonce).nonce is None
        return
    with pytest.raises(ValidationError):
        _payload({}, nonce=nonce)


# --- typed response ---------------------------------------------------------------------------


def test_response_carries_typed_override_values_unchanged():
    from app.schemas.heartbeat import HeartbeatResponse

    overrides = {
        "collector_capture_gate": "time",
        "collector_capture_interval_s": 30.0,
        "collector_gps_enabled": False,
        "gnss_receiver_retries": 5,
        "movement_gate_home_latitude": None,
    }

    dumped = HeartbeatResponse(status="ok", config_overrides=overrides).model_dump(
        exclude_none=True
    )

    assert dumped["config_overrides"] == overrides
    assert dumped["config_overrides"]["collector_gps_enabled"] is False
    assert type(dumped["config_overrides"]["gnss_receiver_retries"]) is int


@pytest.mark.parametrize(
    ("current_config", "expected"),
    [
        ({"system_mode": "manual"}, "manual"),
        ({"system_mode": "waiting"}, None),
        ({"mode": "manual"}, "manual"),
        ({"system_mode": "auto", "mode": "manual"}, "auto"),
        ({"system_mode": "bogus"}, None),
        ({"system_mode": ["auto"]}, None),
        (None, None),
    ],
)
def test_reported_system_mode_accepts_only_manual_and_auto(current_config, expected):
    from app.routers.heartbeat import reported_system_mode

    assert reported_system_mode(current_config) == expected
