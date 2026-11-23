"""Unit tests for CommandCreate: no one-shot command takes a parameter (no SIM ID for
sim-reset-now, the devices have a single SIM; there is no fan control command).
"""
import pytest
from pydantic import ValidationError

from app.schemas.commands import CommandCreate

ONE_SHOT_COMMANDS = [
    "force-upload-now",
    "shutdown-now",
    "sim-reset-now",
    "mode-manual-now",
    "mode-auto-now",
    "start-measuring-now",
    "run-selftest-now",
    "run-gps-fix-test-now",
    "stop-gps-fix-test-now",
    "stop-measuring-now",
    "reboot-now",
    "promote-overrides-now",
]


@pytest.mark.parametrize("command", ONE_SHOT_COMMANDS)
def test_every_allow_listed_command_is_accepted(command):
    created = CommandCreate(command=command)

    assert created.command == command


def test_legacy_waiting_mode_command_is_rejected():
    with pytest.raises(ValidationError):
        CommandCreate(command="mode-waiting-now")


def test_unknown_command_is_rejected():
    with pytest.raises(ValidationError):
        CommandCreate(command="not-a-real-command")


def test_unexpected_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        CommandCreate(command="force-upload-now", speed=50)
