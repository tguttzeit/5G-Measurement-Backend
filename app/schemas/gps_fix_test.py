"""Pydantic schemas for the live GPS-fix-finding diagnostic.

Bounds on the device-pushed fields follow the same reasoning as HeartbeatPayload's
`current_config` size cap (app/routers/heartbeat.py): this is a small, device-authenticated but
otherwise unvalidated payload, so field bounds are the only guardrail against a
misbehaving/compromised device sending nonsense.
"""
from pydantic import BaseModel, Field


class GpsFixTestStatusCreate(BaseModel):
    """A single live status push from a device running run-gps-fix-test-now."""

    num_satellites: int = Field(..., ge=0, le=64, description="Satellites in view")
    has_fix: bool = Field(description="Whether the device has a fix")
    elapsed_s: int = Field(..., ge=0, le=86400, description="Seconds since the test started")


class GpsFixTestStatusResponse(BaseModel):
    """The latest gps-fix-test status for a device, for the dashboard's Find GPS Fix page."""

    run_active: bool = Field(description="False when no recent report exists")
    num_satellites: int | None = Field(default=None, description="Satellites in view")
    has_fix: bool | None = Field(default=None, description="Whether the device has a fix")
    elapsed_s: int | None = Field(default=None, description="Seconds since the test started")
    updated_at: str | None = Field(default=None, description="When the report was received")


__all__ = ["GpsFixTestStatusCreate", "GpsFixTestStatusResponse"]
