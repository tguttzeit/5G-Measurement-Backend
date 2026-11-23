"""Validation of the favorites payload (`PUT /favorite-config-fields`)."""
import pytest
from pydantic import ValidationError

from app.config_override_spec import CONFIG_OVERRIDE_SPEC
from app.schemas.favorite_config_fields import FavoriteConfigFieldsUpdate

KEYS = [spec.key for spec in CONFIG_OVERRIDE_SPEC]


def test_accepts_registry_keys_and_the_empty_list():
    assert FavoriteConfigFieldsUpdate(field_keys=KEYS[:3]).field_keys == KEYS[:3]
    assert FavoriteConfigFieldsUpdate(field_keys=[]).field_keys == []


def test_accepts_every_registry_key_at_once():
    assert len(FavoriteConfigFieldsUpdate(field_keys=KEYS).field_keys) == len(KEYS)


def test_unknown_keys_are_named_in_the_error():
    with pytest.raises(ValidationError, match="not_a_field"):
        FavoriteConfigFieldsUpdate(field_keys=[KEYS[0], "not_a_field"])


def test_system_mode_is_not_a_registry_field_and_is_rejected():
    with pytest.raises(ValidationError):
        FavoriteConfigFieldsUpdate(field_keys=["system_mode"])


def test_duplicates_are_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        FavoriteConfigFieldsUpdate(field_keys=[KEYS[0], KEYS[0]])


def test_more_entries_than_registry_fields_are_rejected_before_per_key_checks():
    with pytest.raises(ValidationError):
        FavoriteConfigFieldsUpdate(field_keys=["x"] * (len(KEYS) + 1))


@pytest.mark.parametrize("value", [None, "a", {}, [1], [None], [["a"]], [True]])
def test_rejects_non_string_lists(value):
    with pytest.raises(ValidationError):
        FavoriteConfigFieldsUpdate(field_keys=value)


def test_field_keys_is_required():
    with pytest.raises(ValidationError):
        FavoriteConfigFieldsUpdate()


def test_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        FavoriteConfigFieldsUpdate(field_keys=[], user_id=2)


def test_overlong_keys_are_rejected_without_being_echoed_in_full():
    with pytest.raises(ValidationError) as excinfo:
        FavoriteConfigFieldsUpdate(field_keys=["a" * 10_000])
    assert "a" * 200 not in str(excinfo.value)
