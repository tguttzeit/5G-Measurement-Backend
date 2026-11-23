"""Pydantic schemas for the device listing API."""
from pydantic import BaseModel, Field


class DeviceSummary(BaseModel):
    device_id: str = Field(description="The device")
    online: bool = Field(description="Heard from within the last 5 minutes")
    last_heartbeat_at: str | None = Field(
        default=None, description="When its last heartbeat was received; null if never"
    )


class DeviceListResponse(BaseModel):
    devices: list[DeviceSummary] = Field(description="Registered devices, ordered by id")


__all__ = ["DeviceSummary", "DeviceListResponse"]
