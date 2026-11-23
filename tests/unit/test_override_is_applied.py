"""`_override_is_applied` decides whether a queued override reached the device by comparing
the queued value to the one in the next `current_config`. Overrides get no ack,
so a kind it cannot compare would never reach the command log's "success" entry.
"""
import pytest

from app.models import CommandType, DeviceCommand
from app.routers.heartbeat import _override_is_applied


def _row(field: str, value) -> DeviceCommand:
    return DeviceCommand(
        device_id="dev", type=CommandType.CONFIG_OVERRIDE, field=field, payload={"value": value}
    )


@pytest.mark.parametrize(
    "wanted,reported",
    [
        (30, 30),
        (30, 30.0),
        (0.1, 0.1 + 1e-12),
        (True, True),
        (False, False),
        ("time", "time"),
        (None, None),
    ],
)
def test_matching_values_are_applied(wanted, reported):
    assert _override_is_applied(_row("f", wanted), {"f": reported})


@pytest.mark.parametrize(
    "wanted,reported",
    [
        (30, 31),
        (True, False),
        (True, 1),
        (1, True),
        (False, 0),
        (0, False),
        ("time", "distance"),
        ("time", "Time"),
        ("1", 1),
        (1, "1"),
        (None, 0),
        (None, "none"),
        (None, 45.0),
        (45.0, None),
    ],
)
def test_differing_values_or_types_are_not_applied(wanted, reported):
    assert not _override_is_applied(_row("f", wanted), {"f": reported})


def test_missing_key_is_not_applied_even_for_a_null_override():
    assert not _override_is_applied(_row("f", None), {"other": 1})


def test_no_current_config_is_not_applied():
    assert not _override_is_applied(_row("f", True), None)
    assert not _override_is_applied(_row("f", True), {})
