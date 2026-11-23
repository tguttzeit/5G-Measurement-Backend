"""Pydantic schemas for measurement datapoints.

Field shapes mirror the device's dataclasses exactly (measurement_software.gnss.gnss_receiver
.Position/.GNSSFix and measurement_software.modems.modem.CellSample), since the device serializes
them with `dataclasses.asdict` — no field renaming or restructuring on the wire.
"""

from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, Field, RootModel

from app.run_ids import is_legacy_run_id


def _reject_legacy_prefix(run_id: str) -> str:
    if is_legacy_run_id(run_id):
        raise ValueError("run_id must not start with the reserved 'legacy-' prefix")
    return run_id


# Device-supplied, stored and later echoed to dashboard users: restricted charset and length. The
# `legacy-` prefix is reserved for the synthetic ids the backend assigns itself (app.run_ids), so
# a device can't pass its own runs off as backfilled ones.
RunId = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9._-]{1,64}$"),
    AfterValidator(_reject_legacy_prefix),
]


class Position(BaseModel):
    """A geographic position in decimal degrees, with optional altitude in meters."""

    latitude: float
    longitude: float
    altitude: float | None = None


class GNSSFix(BaseModel):
    """GNSS fix data from device measurements."""

    position: Position
    num_satellites: int
    placeholder: bool = Field(
        default=False, description="Dummy GPS data from GPS-disabled test run"
    )


class CellSample(BaseModel):
    """Cell measurement sample data."""

    rat: str = Field(max_length=50)  # Radio Access Technology (e.g., LTE, NR5G-NSA, NR5G-SA)
    mcc: int | None = None
    mnc: int | None = None
    cell_id: int | None = None
    pci: int | None = None
    tac: int | None = None
    rsrp: float | None = None
    rsrq: float | None = None
    rssi: float | None = None
    sinr: float | None = None
    band: int | None = None
    channel: int | None = None
    vendor_specific_extras: dict[str, Any] | None = None


class Datapoint(BaseModel):
    """Single measurement datapoint from device."""

    timestamp: datetime
    device_id: str = Field(max_length=255)
    mission_type: str = Field(max_length=255)
    fix: GNSSFix
    cell_sample: CellSample
    run_id: RunId | None = Field(
        default=None,
        description="Identifies the device-side measurement run; omitted by older firmware.",
    )


class DatapointArray(RootModel[list[Datapoint]]):
    """Array of datapoints for bulk upload."""
