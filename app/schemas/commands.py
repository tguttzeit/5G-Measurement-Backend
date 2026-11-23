"""Pydantic schemas for the maintainer-facing config override / command queuing API.

Field/command names here are the allow-list itself: `ConfigOverrideCreate` (built from the
registry in `app/config_override_spec.py`) uses
`extra="forbid"` so any field not explicitly declared (e.g. `upload_host`, `hmac_secret`) is
rejected with 422 automatically, rather than needing a separate allow-list check that could
drift out of sync with what the schema actually accepts. Device identity and secrets
(`device_id`, `hmac_secret`, the device key) are excluded from remote override; the hardware
setting `system_running_on_pi` is the deliberate exception. `system_mode` is reported by the
device but never queueable.
"""
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, create_model, field_validator

from app.config_override_spec import CONFIG_OVERRIDE_SPEC, FieldKind, FieldSpec


class OneShotCommand(StrEnum):
    """Commands the device executes immediately on receipt."""

    FORCE_UPLOAD_NOW = "force-upload-now"
    SHUTDOWN_NOW = "shutdown-now"
    SIM_RESET_NOW = "sim-reset-now"
    MODE_MANUAL_NOW = "mode-manual-now"
    MODE_AUTO_NOW = "mode-auto-now"
    START_MEASURING_NOW = "start-measuring-now"
    RUN_SELFTEST_NOW = "run-selftest-now"
    RUN_GPS_FIX_TEST_NOW = "run-gps-fix-test-now"
    STOP_GPS_FIX_TEST_NOW = "stop-gps-fix-test-now"
    STOP_MEASURING_NOW = "stop-measuring-now"
    REBOOT_NOW = "reboot-now"
    PROMOTE_OVERRIDES_NOW = "promote-overrides-now"


# What a queued override can carry on the wire (also the heartbeat response, which re-sends it).
OverrideValue = float | int | bool | str | None




def _annotation(spec: FieldSpec):
    if spec.kind is FieldKind.ENUM:
        base = Literal[spec.choices]
    elif spec.kind is FieldKind.BOOL:
        base = StrictBool
    else:
        base = Annotated[
            float if spec.kind is FieldKind.FLOAT else int,
            Field(ge=spec.minimum, le=spec.maximum, allow_inf_nan=False, strict=True),
        ]
    return base | None


# Behavior worth knowing beyond type and range; everything else is described by its bounds.
_FIELD_NOTES = {
    "idle_threshold_s": "0 disables the idle end (Auto Mode only), so a run ends only on a "
    "command, a shutdown or power loss",
    "day_end_threshold_s": "Currently has no effect on the device; staged for a later feature",
    "movement_gate_home_latitude": "null clears the override",
    "movement_gate_home_longitude": "null clears the override",
}


def _field_description(spec: FieldSpec) -> str:
    note = _FIELD_NOTES.get(spec.key)
    return f"{note}." if note else "Overrides the device's setting of the same name."


def _reject_null_unless_nullable(cls, value, info):
    if value is None and info.field_name not in _NULLABLE_FIELDS:
        raise ValueError("null is not allowed for this field")
    return value


# Fields where an explicit JSON null is meaningful: it resets the override so the device falls
# back to its config.toml value (the device needs it to clear its home position).
_NULLABLE_FIELDS = frozenset(spec.key for spec in CONFIG_OVERRIDE_SPEC if spec.nullable)

ConfigOverrideCreate = create_model(
    "ConfigOverrideCreate",
    __config__=ConfigDict(extra="forbid"),
    __doc__=(
        "One or more config fields to override, at least one of which must be set. A field "
        "that is not sent is not overridden, and `null` is a value only for the nullable "
        "fields. Types and bounds mirror the device's own validation."
    ),
    __validators__={
        "reject_null_unless_nullable": field_validator("*", mode="before")(
            classmethod(_reject_null_unless_nullable)
        )
    },
    **{
        spec.key: (_annotation(spec), Field(default=None, description=_field_description(spec)))
        for spec in CONFIG_OVERRIDE_SPEC
    },
)


class CommandCreate(BaseModel):
    """A one-shot command to queue. No command takes a parameter."""

    model_config = ConfigDict(extra="forbid")

    command: OneShotCommand = Field(description="The command to queue")


class ConfigOverrideQueuedResponse(BaseModel):
    status: str = Field(description="`ok`")
    config_overrides: dict[str, OverrideValue] = Field(description="The fields that were queued")


class ConfigSchemaField(BaseModel):
    key: str = Field(description="Field name, as used in `POST .../config-overrides`")
    type: FieldKind = Field(description="`float`, `int`, `enum` or `bool`")
    min: float | int | None = Field(description="Lower bound for `float` and `int` fields")
    max: float | int | None = Field(description="Upper bound for `float` and `int` fields")
    values: list[str] | None = Field(description="Allowed values of an `enum` field")
    nullable: bool = Field(description="Whether an explicit `null` resets the override")
    unit: str | None = Field(description="Unit of the value, if it has one")
    requires_confirmation: bool = Field(description="The frontend must confirm before saving")
    no_effect_yet: bool = Field(description="The device accepts the field but does not act on it")


class ConfigSchemaGroup(BaseModel):
    id: str = Field(description="Group id")
    fields: list[ConfigSchemaField] = Field(description="The group's fields, in display order")


class ConfigSchemaResponse(BaseModel):
    groups: list[ConfigSchemaGroup] = Field(description="Groups in display order")


class CommandQueuedResponse(BaseModel):
    status: str = Field(description="`ok`")
    command_id: int = Field(description="Id of the queued command; the device dedupes on it")


class QueueEntry(BaseModel):
    id: int = Field(description="Queue id, for `DELETE .../queue/{id}`")
    type: str = Field(description="`config_override` or `one_shot`")
    field: str | None = Field(description="Config field of an override; null for a command")
    payload: dict = Field(description="`{\"value\": ...}` for an override, `{\"command\": ...}` "
                          "for a command")
    created_at: str = Field(description="When the entry was queued")
    delivered_at: str | None = Field(description="When it was last delivered; null if never")
    expires_at: str | None = Field(description="When a command expires; null for overrides")


class QueueListResponse(BaseModel):
    queue: list[QueueEntry] = Field(description="Queued entries, oldest first")


class CommandLogItem(BaseModel):
    id: int = Field(description="Log entry id")
    occurred_at: str = Field(description="When it happened")
    device_id: str = Field(description="The device")
    direction: str = Field(description="`to_device` or `from_device`")
    kind: str = Field(description="`config` or `command`")
    name: str = Field(description="Config field or command name")
    command_id: int | None = Field(description="Queue id of the command or override")
    status: str = Field(description="Queue event or acknowledgement status")
    detail: str | None = Field(description="`= <value>` for a config override, or error text")


class CommandLogResponse(BaseModel):
    entries: list[CommandLogItem] = Field(description="Entries, newest first")


class CommandStatusEntry(BaseModel):
    command_id: int = Field(description="Queue id of the command or override")
    kind: str = Field(description="`config` or `command`")
    name: str = Field(description="Config field or command name")
    detail: str | None = Field(description="`= <value>` for a config override")
    state: str = Field(
        description="`queued`, `delivered`, `received`, `success`, `failed`, `not_applicable`, "
        "`promoted`, `removed` or `expired`"
    )
    complete: bool = Field(
        description="True once nothing more is expected: a result, or it was removed or expired"
    )
    in_queue: bool = Field(description="Whether it is still in the queue")
    queued_at: str | None = Field(description="When it was queued")
    delivered_at: str | None = Field(description="When it was first delivered")
    received_at: str | None = Field(description="When the device acknowledged receipt")
    result_at: str | None = Field(description="When the device reported the result")
    removed_at: str | None = Field(description="When a maintainer removed it from the queue")
    promoted_at: str | None = Field(description="When `promote-overrides-now` promoted it")
    expired_at: str | None = Field(description="When it expired")
    expires_at: str | None = Field(description="When it expires; null for overrides")
    error: str | None = Field(
        description="Reason of a `failed` or `not_applicable` result; null otherwise"
    )


COMMAND_DISMISS_MAX_IDS = 500


class CommandDismissRequest(BaseModel):
    """The ids a maintainer's "Delete shown" asks to hide; the server decides which count."""

    model_config = ConfigDict(extra="forbid")

    command_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(
        min_length=1,
        max_length=COMMAND_DISMISS_MAX_IDS,
        description="Command ids to hide; only finished commands of the device count",
    )


class CommandDismissResponse(BaseModel):
    dismissed: list[int] = Field(description="The ids that were hidden, ascending")


class CommandStatusResponse(BaseModel):
    items: list[CommandStatusEntry] = Field(description="Commands and overrides, newest first")
    # What a shutdown-now's success is inferred from: the page counts the silence since
    # `last_heartbeat_at` up to `shutdown_confirm_seconds`, the effective span in
    # both modes (`shutdown_confirm_intervals` is the effective number of heartbeat intervals,
    # fractional for a fixed time span); `shutdown_fail_heartbeats` heartbeats after the ack mean
    # it did not shut down.
    last_heartbeat_at: str | None = Field(description="When the device last sent a heartbeat")
    heartbeat_interval_s: float = Field(description="The device's heartbeat interval in seconds")
    shutdown_confirm_mode: Literal["intervals", "seconds"] = Field(
        description="Which shutdown confirmation rule applies"
    )
    shutdown_confirm_intervals: float = Field(
        description="The confirmation span in heartbeat intervals; fractional in `seconds` mode"
    )
    shutdown_confirm_seconds: float = Field(
        description="The confirmation span in seconds, in both modes"
    )
    shutdown_fail_heartbeats: int = Field(
        description="Heartbeats after the acknowledgement that mean the shutdown failed"
    )


__all__ = [
    "COMMAND_DISMISS_MAX_IDS",
    "CommandDismissRequest",
    "CommandDismissResponse",
    "CommandStatusEntry",
    "CommandStatusResponse",
    "CommandLogItem",
    "CommandLogResponse",
    "OneShotCommand",
    "ConfigOverrideCreate",
    "OverrideValue",
    "CommandCreate",
    "ConfigOverrideQueuedResponse",
    "ConfigSchemaField",
    "ConfigSchemaGroup",
    "ConfigSchemaResponse",
    "CommandQueuedResponse",
    "QueueEntry",
    "QueueListResponse",
]
