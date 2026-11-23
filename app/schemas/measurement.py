"""Pydantic schemas for the map/heatmap query API.

Response shape deliberately carries only position and the requested metric's aggregated value —
timestamps/device IDs/other metadata never appear here, even though the underlying
`measurements` rows have them.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import get_settings


class Metric(StrEnum):
    """Cell quality metric selectable for the heatmap/export."""

    RSRP = "rsrp"
    RSRQ = "rsrq"
    SINR = "sinr"


class ViewMode(StrEnum):
    """View modes of `GET /measurements/detailed`: grid-aggregated points or individual rows."""

    AGGREGATE = "aggregate"
    RAW = "raw"


class ExportFormat(StrEnum):
    """Export formats implemented server-side.

    PNG is deliberately absent - it's a client-side capture of the rendered map, not a server
    format.
    """

    CSV = "csv"
    GEOJSON = "geojson"


class MeasurementExtent(BaseModel):
    bbox: tuple[float, float, float, float] | None = Field(
        default=None,
        description="min_lon,min_lat,max_lon,max_lat of matching rows, or null if none match",
    )


class HeatmapPointProperties(BaseModel):
    value: float = Field(description="Average of the requested metric within this grid cell")
    count: int = Field(description="Number of measurement rows aggregated into this point")


class GeoJSONPointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float] = Field(description="[longitude, latitude]")


class HeatmapFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONPointGeometry
    properties: HeatmapPointProperties


class HeatmapFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[HeatmapFeature]


class RawPointProperties(BaseModel):
    """One individual measurement, for logged-in users. All three metrics are carried together;
    the uploaded raw payload never is."""

    id: int = Field(description="Measurement id, only to reference a selection for export")
    device_id: str = Field(description="Device that recorded the measurement")
    timestamp: datetime = Field(description="When the measurement was taken")
    rsrp: float | None = Field(description="RSRP; null if not measured")
    rsrq: float | None = Field(description="RSRQ; null if not measured")
    sinr: float | None = Field(description="SINR; null if not measured")


class RawFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONPointGeometry
    properties: RawPointProperties


class RawFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[RawFeature]


class PublicPointProperties(BaseModel):
    """One individual measurement with position and metric values only; it has no device,
    timestamp or run field."""

    id: int = Field(description="Measurement id, only to reference a selection for export")
    rsrp: float | None = Field(description="RSRP; null if not measured")
    rsrq: float | None = Field(description="RSRQ; null if not measured")
    sinr: float | None = Field(description="SINR; null if not measured")


class PublicPointFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONPointGeometry
    properties: PublicPointProperties


class PublicPointFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[PublicPointFeature]


class SelectionExportRequest(BaseModel):
    """Body of `POST /measurements/export-selection`."""

    model_config = ConfigDict(extra="forbid")

    ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(
        min_length=1,
        description="Measurement ids (the `id` of the raw point features); deduplicated, with a "
        "server-side maximum of distinct ids",
    )
    format: ExportFormat = Field(description="`csv` or `geojson`")

    @field_validator("ids")
    @classmethod
    def deduplicate_and_limit(cls, ids: list[int]) -> list[int]:
        distinct_ids = list(dict.fromkeys(ids))
        if len(distinct_ids) > get_settings().selection_export_max_ids:
            raise ValueError("too many ids in selection")
        return distinct_ids


class SelectionExportProperties(BaseModel):
    """Only the fields a selection export may carry - no device_id/timestamp/run_id/raw_data and
    not even the measurement id."""

    rsrp: float | None = Field(description="RSRP; null if not measured")
    rsrq: float | None = Field(description="RSRQ; null if not measured")
    sinr: float | None = Field(description="SINR; null if not measured")
    mission_type: str = Field(description="`ground` or `drone`")
    campaign: str | None = Field(description="Name of the point's run's campaign, if any")


class SelectionExportFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONPointGeometry
    properties: SelectionExportProperties


class SelectionExportFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[SelectionExportFeature]
