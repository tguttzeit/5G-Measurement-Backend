"""Pydantic schemas for the latency-result map query API.

The public heatmap/extent endpoints reuse `HeatmapFeatureCollection`/`MeasurementExtent` from
`app.schemas.measurement` unchanged; only the authenticated raw view needs its own shape, since
each row has two positions (a line) and five metric values instead of one point and three.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class LatencyMetric(StrEnum):
    """Latency or throughput metric selectable for the map."""

    BASELINE_RTT_MS = "baseline_rtt_ms"
    RTT_UNDER_LOAD_MS = "rtt_under_load_ms"
    RTT_P99_MS = "rtt_p99_ms"
    DOWNLOAD_MBITS_S = "download_mbits_s"
    UPLOAD_MBITS_S = "upload_mbits_s"


class GeoJSONLineGeometry(BaseModel):
    type: Literal["LineString"] = "LineString"
    coordinates: tuple[tuple[float, float], tuple[float, float]] = Field(
        description="[[start_lon, start_lat], [end_lon, end_lat]]"
    )


class LatencyRawProperties(BaseModel):
    """One latency test result for logged-in users, carrying all five metrics together."""

    device_id: str = Field(description="Device that ran the test")
    test_type: str = Field(description="Kind of latency test")
    start_timestamp: datetime = Field(description="When the test started")
    end_timestamp: datetime = Field(description="When the test ended")
    baseline_rtt_ms: float | None = Field(description="Baseline round-trip time in ms")
    rtt_under_load_ms: float | None = Field(description="Round-trip time under load in ms")
    rtt_p99_ms: float | None = Field(description="99th percentile round-trip time in ms")
    download_mbits_s: float | None = Field(description="Download throughput in Mbit/s")
    upload_mbits_s: float | None = Field(description="Upload throughput in Mbit/s")


class LatencyRawFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONLineGeometry
    properties: LatencyRawProperties


class LatencyRawFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[LatencyRawFeature]


class LatencyPublicPointProperties(BaseModel):
    """One latency test result's metric values only; it has no device, timestamp, test type
    or run field."""

    baseline_rtt_ms: float | None = Field(description="Baseline round-trip time in ms")
    rtt_under_load_ms: float | None = Field(description="Round-trip time under load in ms")
    rtt_p99_ms: float | None = Field(description="99th percentile round-trip time in ms")
    download_mbits_s: float | None = Field(description="Download throughput in Mbit/s")
    upload_mbits_s: float | None = Field(description="Upload throughput in Mbit/s")


class LatencyPublicPointFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONLineGeometry
    properties: LatencyPublicPointProperties


class LatencyPublicPointFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[LatencyPublicPointFeature]
