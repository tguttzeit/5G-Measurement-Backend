"""Unit tests for GpsFixTestStatusCreate's field bounds.

Bounds guard against a misbehaving/compromised device sending nonsense, since this payload is
otherwise unvalidated - same reasoning as HeartbeatPayload's current_config size cap.
"""
import pytest
from pydantic import ValidationError

from app.schemas.gps_fix_test import GpsFixTestStatusCreate


def test_accepts_a_valid_payload():
    payload = GpsFixTestStatusCreate(num_satellites=7, has_fix=True, elapsed_s=42)

    assert payload.num_satellites == 7
    assert payload.has_fix is True
    assert payload.elapsed_s == 42


@pytest.mark.parametrize("num_satellites", [-1, 65])
def test_rejects_num_satellites_out_of_bounds(num_satellites):
    with pytest.raises(ValidationError):
        GpsFixTestStatusCreate(num_satellites=num_satellites, has_fix=False, elapsed_s=0)


@pytest.mark.parametrize("elapsed_s", [-1, 86401])
def test_rejects_elapsed_s_out_of_bounds(elapsed_s):
    with pytest.raises(ValidationError):
        GpsFixTestStatusCreate(num_satellites=0, has_fix=False, elapsed_s=elapsed_s)


def test_requires_all_fields():
    with pytest.raises(ValidationError):
        GpsFixTestStatusCreate(num_satellites=7, has_fix=True)
