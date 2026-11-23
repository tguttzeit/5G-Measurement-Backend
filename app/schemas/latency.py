"""Pydantic schema for latency test results.

Field shapes mirror the device's `measurement_software.core.latency_result.LatencyResult`
dataclass exactly, since the device serializes it with `dataclasses.asdict` — no field
renaming or restructuring on the wire. `start_fix`/`end_fix` reuse `GNSSFix`/`Position` from
`app.schemas.datapoint`, the same nested shape `Datapoint.fix` uses.

The five RTT/throughput fields are independently optional with no cross-field requiredness
rule tying them to `test_type` — the device dataclass itself declares them that way, with no
`__post_init__` validation, so this schema doesn't invent a stricter rule.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, RootModel, field_validator

from app.schemas.datapoint import GNSSFix, RunId


class LatencyTestType(StrEnum):
    """Kind of latency test a `LatencyResult` reports on."""

    BASELINE = "baseline"
    UNDER_LOAD = "under_load"


class LatencyResult(BaseModel):
    """A single latency test result from device."""

    test_type: LatencyTestType = Field(description="Kind of latency test")
    flent_test: str = Field(max_length=255, description="Name of the flent test that ran")
    device_id: str = Field(max_length=255, description="Must be the authenticated device")
    mission_type: str = Field(max_length=255, description="`ground` or `drone`")
    start_timestamp: str = Field(description="ISO 8601 timestamp of the test start")
    end_timestamp: str = Field(description="ISO 8601 timestamp of the test end")
    start_fix: GNSSFix = Field(description="Position when the test started")
    end_fix: GNSSFix = Field(description="Position when the test ended")
    baseline_rtt_ms: float | None = Field(default=None, description="Baseline round-trip time, ms")
    rtt_under_load_ms: float | None = Field(
        default=None, description="Round-trip time under load, ms"
    )
    rtt_p99_ms: float | None = Field(
        default=None, description="99th percentile round-trip time, ms"
    )
    download_mbits_s: float | None = Field(default=None, description="Download throughput, Mbit/s")
    upload_mbits_s: float | None = Field(default=None, description="Upload throughput, Mbit/s")
    idempotency_key: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Client-generated dedup key, scoped to the submitting device. Omitted entirely by "
            "older device builds that don't send one yet - no dedup is attempted for those."
        ),
    )

    run_id: RunId | None = Field(
        default=None,
        description="Identifies the device-side measurement run; omitted by older firmware.",
    )

    @field_validator("start_timestamp", "end_timestamp")
    @classmethod
    def _must_be_iso8601(cls, value: str) -> str:
        """Reject unparseable timestamps here (422) rather than in the router (500)."""
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class LatencyResultArray(RootModel[list[LatencyResult]]):
    """Array of latency test results for bulk upload."""
