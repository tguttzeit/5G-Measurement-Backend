"""Pydantic schemas for the per-user favorite config fields API."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from app.config_override_spec import CONFIG_OVERRIDE_SPEC

REGISTRY_KEYS = frozenset(spec.key for spec in CONFIG_OVERRIDE_SPEC)
MAX_FAVORITES = len(CONFIG_OVERRIDE_SPEC)
# Keeps a rejected key short enough to name in the error message.
MAX_KEY_LENGTH = 100


class FavoriteConfigFieldsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_keys: list[Annotated[StrictStr, Field(max_length=MAX_KEY_LENGTH)]] = Field(
        max_length=MAX_FAVORITES,
        description="The complete set of favorite field keys; replaces the stored one",
    )

    @field_validator("field_keys")
    @classmethod
    def _keys_are_unique_registry_fields(cls, keys: list[str]) -> list[str]:
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate config field keys")
        unknown = [key for key in keys if key not in REGISTRY_KEYS]
        if unknown:
            raise ValueError(f"unknown config field keys: {', '.join(unknown)}")
        return keys


class FavoriteConfigFields(BaseModel):
    field_keys: list[str] = Field(description="Registry field keys, in form display order")
