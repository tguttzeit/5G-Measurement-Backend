"""Pydantic schemas for request/response validation."""
from pydantic import BaseModel, Field


class HeartbeatPayload(BaseModel):
    """Schema for the heartbeat payload from devices."""

    since_run_start: dict = Field(..., alias="since_run_start")
    pipeline_broken: bool
    storage: dict

    @property
    def datapoints_total(self) -> int:
        return self.since_run_start.get("datapoints_total", 0)

    @property
    def datapoints_good(self) -> int:
        return self.since_run_start.get("good", 0)

    @property
    def datapoints_bad(self) -> int:
        return self.since_run_start.get("bad", 0)

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

    status: str
    message: str | None = None


class DeviceHeartbeatSummary(BaseModel):
    """Summary of the latest heartbeat for a device (for dashboard)."""

    device_id: str
    received_at: str
    datapoints_total: int
    datapoints_good: int
    datapoints_bad: int
    datapoints_invalid: int
    pipeline_broken: bool
    storage_pending_files: int
    storage_disk_free_bytes: int


class HeartbeatListResponse(BaseModel):
    """Response schema for listing latest heartbeats."""

    heartbeats: list[DeviceHeartbeatSummary]
