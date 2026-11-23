"""Pydantic schemas for heartbeat request/response validation."""
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.commands import OverrideValue

# Reasonable ceiling on GNSS satellites in view - well above what any real constellation
# combination (GPS+GLONASS+Galileo+BeiDou, etc.) could plausibly report, so a device sending
# a sane value is never rejected while a garbled/malicious one is.
_MAX_PLAUSIBLE_SATELLITES = 64

_MAX_FINGERPRINT_LENGTH = 256
_MAX_ACTION_LENGTH = 64
_MAX_ERROR_COUNTER = 1_000_000


class RunPhase(StrEnum):
    """The device's current run-loop phase."""

    RECOVERING_PENDING_DATA = "recovering_pending_data"
    WAITING_FOR_GPS_FIX = "waiting_for_gps_fix"
    WAITING_FOR_MOVEMENT = "waiting_for_movement"
    MANUAL_MODE_IDLE = "manual_mode_idle"
    # Idle after a crash was recovered; sent with the same crash details as `critical_error`.
    RECOVERY_IDLE = "recovery_idle"
    STARTING_UP = "starting_up"
    STOPPING = "stopping"
    ACTIVE_MEASURING = "active_measuring"
    FINALIZING = "finalizing"
    DONE = "done"
    # The device's last heartbeat before shutdown-now/reboot-now takes effect -
    # never followed by another phase in the same boot (shutdown), or followed
    # by a fresh run after the device comes back up (reboot).
    SHUTTING_DOWN = "shutting_down"
    REBOOTING = "rebooting"
    # The device entered maintenance mode after repeated unhandled errors; sent with a
    # `critical_error` object, retried until delivered.
    CRITICAL_ERROR = "critical_error"


class ExecutedCommand(BaseModel):
    """The device's report on one delivered one-shot command. It is sent again on every
    heartbeat for as long as the command keeps being delivered."""

    id: int = Field(description="Id of the delivered command")
    command: str = Field(description="Name of the command, a plain string")
    status: str = Field(
        description="`success`, `failed`, `not_applicable` or `received`; a plain string, and "
        "an unknown value is logged and leaves the command queued"
    )
    error: str | None = Field(
        default=None, description="Null on success, otherwise the failure or not-applicable reason"
    )


class GpsFixStatus(BaseModel):
    """Live GPS-fix state as reported in a heartbeat."""

    has_fix: bool = Field(description="Whether the device currently has a GPS fix")
    num_satellites: int | None = Field(
        default=None, ge=0, le=_MAX_PLAUSIBLE_SATELLITES, description="Satellites in view"
    )
    fix_age_s: float | None = Field(default=None, ge=0, description="Age of the fix in seconds")


class CriticalError(BaseModel):
    """Details of the unhandled error behind the `critical_error` and `recovery_idle` run
    phases. Every field is typed and bounded, and unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str | None = Field(
        default=None, max_length=_MAX_FINGERPRINT_LENGTH, description="Identifies the error"
    )
    same_error_count: int = Field(
        ge=0, le=_MAX_ERROR_COUNTER, description="How often the same error occurred in a row"
    )
    consecutive_reboots: int = Field(
        ge=0, le=_MAX_ERROR_COUNTER, description="Reboots the device has done because of it"
    )
    action: str = Field(max_length=_MAX_ACTION_LENGTH, description="What the device did about it")


class HeartbeatPayload(BaseModel):
    """Schema for the heartbeat payload from devices."""

    since_run_start: dict = Field(
        ..., alias="since_run_start", description="Datapoint counters since the run started"
    )
    pipeline_broken: bool = Field(description="Whether the measurement pipeline is broken")
    storage: dict = Field(description="Upload backlog and free disk space of the device")
    # Device's live in-effect config values, keyed by the same field names as
    # ConfigOverrideCreate. Optional and unvalidated (free-form dict) - see
    # app/routers/heartbeat.py's size cap for the one guardrail applied to it.
    current_config: dict | None = Field(
        default=None,
        description="The device's live in-effect config values, keyed like the config "
        "overrides plus `system_mode`; at most 4096 bytes",
    )
    # Both optional/nullable so an older device build that doesn't send them yet still
    # validates.
    run_phase: RunPhase | None = Field(default=None, description="Current run-loop phase")
    gps_fix: GpsFixStatus | None = Field(default=None, description="Live GPS-fix state")
    # Only sent together with run_phase "critical_error" or "recovery_idle".
    critical_error: CriticalError | None = Field(
        default=None,
        description="Only sent together with the `critical_error` or `recovery_idle` run phase",
    )
    # Results for one-shot commands the device has executed.
    # Optional/nullable so an older device build that doesn't report acks yet still validates.
    executed_commands: list[ExecutedCommand] | None = Field(
        default=None,
        description="Results of delivered one-shot commands; omitted when there is nothing "
        "to report",
    )
    # Random per-request challenge: echoed back inside the signed response so the
    # device can tell a fresh response from a replayed one. Bounded because it ends up inside
    # a signed body; None for older device builds, which then get no nonce back.
    nonce: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9]{1,64}$",
        description="Random per-request value, 1 to 64 characters of `[A-Za-z0-9]`; echoed "
        "inside the signed response",
    )

    @property
    def datapoints_total(self) -> int:
        return self.since_run_start.get("datapoints_total", 0)

    @property
    def datapoints_valid(self) -> int:
        # Devices that predate the valid/invalid split report good + bad instead.
        if "valid" in self.since_run_start:
            return self.since_run_start["valid"]
        return self.since_run_start.get("good", 0) + self.since_run_start.get("bad", 0)

    @property
    def datapoints_invalid(self) -> int:
        return self.since_run_start.get("invalid", 0)

    @property
    def storage_pending_files(self) -> int:
        return self.storage.get("pending_files", 0)

    @property
    def storage_disk_free_bytes(self) -> int:
        return self.storage.get("disk_free_bytes", 0)


class HeartbeatResponse(BaseModel):
    """Response schema for heartbeat ingestion."""

    status: str = Field(description="`ok`")
    message: str | None = Field(default=None, description="Human-readable outcome")
    # Currently active, allow-listed config field overrides for this device,
    # merged over its local config device-side; omitted entirely when none are queued.
    # Values are numbers, booleans and enum strings; null resets an override (home position).
    config_overrides: dict[str, OverrideValue] | None = Field(
        default=None,
        description="Active config overrides, field to value; null resets an override. "
        "Omitted when none are queued",
    )
    # Queued one-shot commands not yet removed; delivered at-least-once, the
    # device is expected to dedupe on `id`. Omitted entirely when none are queued.
    commands: list[dict] | None = Field(
        default=None,
        description="Queued one-shot commands as `{id, command}`, delivered at least once; "
        "omitted when none are queued",
    )
    # The request's nonce, echoed inside the signed body; omitted when the
    # request carried none.
    nonce: str | None = Field(
        default=None, description="The request's nonce, echoed; omitted if the request had none"
    )
    # HMAC-SHA256 of this response body excluding this field.
    signature: str | None = Field(
        default=None,
        description="`hmac-sha256:<hex digest>` over the response body excluding this field, "
        "keyed by the device's own HMAC secret",
    )


class DeviceHeartbeatSummary(BaseModel):
    """Summary of the latest heartbeat for a device (for dashboard)."""

    device_id: str = Field(description="The device")
    received_at: str = Field(description="When the heartbeat was received")
    datapoints_total: int = Field(description="Datapoints since the run started")
    datapoints_valid: int = Field(description="Valid datapoints since the run started")
    datapoints_invalid: int = Field(description="Invalid datapoints since the run started")
    pipeline_broken: bool = Field(description="Whether the measurement pipeline is broken")
    storage_pending_files: int = Field(description="Files waiting for upload")
    storage_disk_free_bytes: int = Field(description="Free disk space of the device in bytes")
    # Only populated for superuser callers - same trust bar as writing config
    # overrides. None for ordinary authenticated users hitting this for MissionStatusPage.
    current_config: dict | None = Field(
        default=None,
        description="The device's live in-effect config as last reported; superusers only, "
        "null for other callers and while the device has reported none",
    )
    # Run phase / GPS-fix status - unlike current_config these carry no
    # config-write-equivalent sensitivity, so visible to any authenticated dashboard caller.
    run_phase: str | None = Field(default=None, description="Current run-loop phase")
    gps_fix: dict | None = Field(default=None, description="Live GPS-fix state")
    # Superuser-only: the fingerprint carries internal function names.
    critical_error: dict | None = Field(
        default=None, description="Details of a critical error; superusers only"
    )
    # "manual" / "auto" / None, derived from the
    # stored current_config so that callers who can't read current_config can still see the mode.
    system_mode: str | None = Field(
        default=None, description="`manual` or `auto`; visible to every caller"
    )


class HeartbeatListResponse(BaseModel):
    """Response schema for listing latest heartbeats."""

    heartbeats: list[DeviceHeartbeatSummary]
