"""Validation of the raw-row-cap setting payload (`PUT /settings/raw-row-cap`)."""
import pytest
from pydantic import ValidationError

from app.schemas.settings import MAX_RAW_ROW_CAP, RawRowCapUpdate


@pytest.mark.parametrize("value", [1, 5000, MAX_RAW_ROW_CAP, None])
def test_accepts_null_or_an_integer_within_bounds(value):
    assert RawRowCapUpdate(value=value).value == value


@pytest.mark.parametrize(
    "value", [0, -1, MAX_RAW_ROW_CAP + 1, 10**30, True, False, 5.0, 5.5, "5000", [], {}]
)
def test_rejects_everything_else(value):
    with pytest.raises(ValidationError):
        RawRowCapUpdate(value=value)


def test_value_is_required_so_omission_is_not_mistaken_for_unlimited():
    with pytest.raises(ValidationError):
        RawRowCapUpdate()


def test_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        RawRowCapUpdate(value=1, extra="x")
