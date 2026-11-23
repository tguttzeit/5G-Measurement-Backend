"""The shutdown-confirmation setting payload (`PUT /settings/shutdown-confirmation`) and the
silence it translates into for `confirm_shutdowns`."""
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.command_status import DEFAULT_SHUTDOWN_CONFIRMATION, required_silence
from app.schemas.settings import ShutdownConfirmation


def test_default_is_four_heartbeat_intervals():
    assert ShutdownConfirmation() == DEFAULT_SHUTDOWN_CONFIRMATION
    assert (DEFAULT_SHUTDOWN_CONFIRMATION.mode, DEFAULT_SHUTDOWN_CONFIRMATION.intervals) == (
        "intervals",
        4,
    )
    assert DEFAULT_SHUTDOWN_CONFIRMATION.seconds == 60


@pytest.mark.parametrize("mode", ["intervals", "seconds"])
def test_accepts_both_modes(mode):
    assert ShutdownConfirmation(mode=mode, intervals=4, seconds=60).mode == mode


@pytest.mark.parametrize("intervals", [1, 4, 20])
def test_accepts_intervals_within_bounds(intervals):
    assert ShutdownConfirmation(mode="intervals", intervals=intervals).intervals == intervals


@pytest.mark.parametrize("intervals", [0, -1, 21, 4.0, 4.5, True, False, "4", None, [], 10**30])
def test_rejects_invalid_intervals(intervals):
    with pytest.raises(ValidationError):
        ShutdownConfirmation(mode="intervals", intervals=intervals)


@pytest.mark.parametrize("seconds", [10, 10.5, 60, 3600, 3600.0])
def test_accepts_seconds_within_bounds(seconds):
    assert ShutdownConfirmation(mode="seconds", seconds=seconds).seconds == seconds


@pytest.mark.parametrize(
    "seconds",
    [
        9, 9.99, 3600.01, 3601, 0, -5, float("nan"), float("inf"), float("-inf"),
        True, False, "60", None,
    ],
)
def test_rejects_invalid_seconds(seconds):
    with pytest.raises(ValidationError):
        ShutdownConfirmation(mode="seconds", seconds=seconds)


@pytest.mark.parametrize("mode", ["interval", "", "SECONDS", None, 1, True])
def test_rejects_unknown_modes(mode):
    with pytest.raises(ValidationError):
        ShutdownConfirmation(mode=mode)


def test_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ShutdownConfirmation(mode="intervals", extra="x")


def test_required_silence_scales_with_the_heartbeat_interval_in_intervals_mode():
    setting = ShutdownConfirmation(mode="intervals", intervals=3, seconds=999)

    assert required_silence(setting, interval_s=15) == timedelta(seconds=45)
    assert required_silence(setting, interval_s=60) == timedelta(seconds=180)


def test_required_silence_ignores_the_heartbeat_interval_in_seconds_mode():
    setting = ShutdownConfirmation(mode="seconds", intervals=20, seconds=90)

    assert required_silence(setting, interval_s=15) == timedelta(seconds=90)
    assert required_silence(setting, interval_s=600) == timedelta(seconds=90)


def test_default_required_silence_is_unchanged_from_before_the_setting_existed():
    assert required_silence(DEFAULT_SHUTDOWN_CONFIRMATION, interval_s=15) == timedelta(seconds=60)
