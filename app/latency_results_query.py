"""Bbox-filtered, grid-aggregated queries over latency test results for the map.

Mirrors `app.measurements_query`, reusing its bbox parsing, campaign resolution and grid
sizing. The difference: a latency result has two positions (`start_fix`/`end_fix`, stored as
JSONB) instead of one. Aggregation and bbox filtering use the midpoint of the two; only the raw
view returns both ends.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.app_settings import get_authenticated_raw_row_cap
from app.measurements_query import (
    GRID_ORIGIN_LAT,
    GRID_ORIGIN_LON,
    RAW_ROW_CAP,
    AggregatedGrid,
    AggregatedPoint,
    BoundingBox,
    Extent,
    _grid_cell_size,
    fetch_capped_rows,
    resolve_campaign,
    resolve_optional_campaign_id,
    run_filter,
)
from app.models.latency import LatencyTestResult
from app.schemas.latency_map import LatencyMetric


@dataclass(frozen=True)
class LatencyPublicLine:
    start_longitude: float
    start_latitude: float
    end_longitude: float
    end_latitude: float
    baseline_rtt_ms: float | None
    rtt_under_load_ms: float | None
    rtt_p99_ms: float | None
    download_mbits_s: float | None
    upload_mbits_s: float | None


@dataclass(frozen=True)
class LatencyRawLine:
    start_longitude: float
    start_latitude: float
    end_longitude: float
    end_latitude: float
    device_id: str
    test_type: str
    start_timestamp: datetime
    end_timestamp: datetime
    baseline_rtt_ms: float | None
    rtt_under_load_ms: float | None
    rtt_p99_ms: float | None
    download_mbits_s: float | None
    upload_mbits_s: float | None


def _fix_coordinate(fix_column, axis: str) -> ColumnElement[float]:
    return fix_column["position"][axis].as_float()


_START_LON = _fix_coordinate(LatencyTestResult.start_fix, "longitude")
_START_LAT = _fix_coordinate(LatencyTestResult.start_fix, "latitude")
_END_LON = _fix_coordinate(LatencyTestResult.end_fix, "longitude")
_END_LAT = _fix_coordinate(LatencyTestResult.end_fix, "latitude")
_MID_LON = (_START_LON + _END_LON) / 2
_MID_LAT = (_START_LAT + _END_LAT) / 2


def _row_conditions(
    metric_col,
    campaign_id: int | None,
    device_id: str | None,
    mission_type: str | None,
    bbox: BoundingBox | None = None,
    run_id: str | None = None,
) -> list:
    """Shared WHERE conditions. Rows with a placeholder (GPS-disabled) fix at either end are
    always excluded, and the selected metric's column must be non-null - which is also what
    restricts e.g. `baseline_rtt_ms` to baseline test runs."""
    conditions = [
        LatencyTestResult.start_fix["placeholder"].as_boolean().isnot(True),
        LatencyTestResult.end_fix["placeholder"].as_boolean().isnot(True),
        metric_col.isnot(None),
    ]
    if bbox is not None:
        conditions += [
            _MID_LON >= bbox.min_lon,
            _MID_LON <= bbox.max_lon,
            _MID_LAT >= bbox.min_lat,
            _MID_LAT <= bbox.max_lat,
        ]
    conditions.append(run_filter(LatencyTestResult, campaign_id, mission_type, run_id))
    if device_id is not None:
        conditions.append(LatencyTestResult.device_id == device_id)
    return conditions


def query_latency_heatmap(
    db: Session,
    bbox: BoundingBox,
    metric: LatencyMetric,
    device_id: str | None = None,
    mission_type: str | None = None,
    campaign_id: int | None = None,
) -> AggregatedGrid:
    """Public: midpoint-positioned results grid-averaged per cell, scoped to exactly one
    campaign (see `resolve_campaign`). Carries only position, average and count."""
    cell_width, cell_height = _grid_cell_size(bbox)
    campaign = resolve_campaign(db, campaign_id)
    if campaign is None:
        return AggregatedGrid(cell_width=cell_width, cell_height=cell_height, points=[])

    metric_col = getattr(LatencyTestResult, metric.value)
    conditions = _row_conditions(metric_col, campaign.id, device_id, mission_type, bbox)
    cell_x = func.floor((_MID_LON - GRID_ORIGIN_LON) / cell_width)
    cell_y = func.floor((_MID_LAT - GRID_ORIGIN_LAT) / cell_height)

    query = (
        select(
            cell_x.label("cell_x"),
            cell_y.label("cell_y"),
            func.avg(metric_col).label("avg_value"),
            func.count().label("point_count"),
        )
        .where(*conditions)
        .group_by("cell_x", "cell_y")
    )

    return AggregatedGrid(
        cell_width=cell_width,
        cell_height=cell_height,
        points=[
            AggregatedPoint(
                longitude=GRID_ORIGIN_LON + (int(row.cell_x) + 0.5) * cell_width,
                latitude=GRID_ORIGIN_LAT + (int(row.cell_y) + 0.5) * cell_height,
                value=row.avg_value,
                count=row.point_count,
            )
            for row in db.execute(query)
        ],
    )


def query_latency_extent(
    db: Session,
    metric: LatencyMetric,
    device_id: str | None = None,
    mission_type: str | None = None,
    campaign_id: int | None = None,
) -> Extent | None:
    """Public: the true min/max lat/lon over both ends of every matching result, for fitting
    the initial map view. `None` when no campaign has runs or no row matches."""
    campaign = resolve_campaign(db, campaign_id)
    if campaign is None:
        return None

    metric_col = getattr(LatencyTestResult, metric.value)
    conditions = _row_conditions(metric_col, campaign.id, device_id, mission_type)
    row = db.execute(
        select(
            func.least(func.min(_START_LON), func.min(_END_LON)),
            func.least(func.min(_START_LAT), func.min(_END_LAT)),
            func.greatest(func.max(_START_LON), func.max(_END_LON)),
            func.greatest(func.max(_START_LAT), func.max(_END_LAT)),
        ).where(*conditions)
    ).one()
    min_lon, min_lat, max_lon, max_lat = row
    if min_lon is None:
        return None

    return Extent(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)


def query_latency_raw(
    db: Session,
    bbox: BoundingBox,
    metric: LatencyMetric,
    device_id: str | None = None,
    mission_type: str | None = None,
    campaign_id: int | None = None,
    cap: int | None = None,
    run_id: str | None = None,
) -> list[LatencyRawLine]:
    """Authenticated: individual, ungrouped results whose midpoint is within the bbox. Same
    configurable row cap (unlimited by default) and query-level overflow handling as
    `query_raw_points`; `idempotency_key` and the full fix objects are never returned."""
    if cap is None:
        cap = get_authenticated_raw_row_cap(db)
    scoped_campaign_id = resolve_optional_campaign_id(db, campaign_id)
    metric_col = getattr(LatencyTestResult, metric.value)
    conditions = _row_conditions(
        metric_col, scoped_campaign_id, device_id, mission_type, bbox, run_id
    )

    query = (
        select(
            _START_LON.label("start_longitude"),
            _START_LAT.label("start_latitude"),
            _END_LON.label("end_longitude"),
            _END_LAT.label("end_latitude"),
            LatencyTestResult.device_id,
            LatencyTestResult.test_type,
            LatencyTestResult.start_timestamp,
            LatencyTestResult.end_timestamp,
            LatencyTestResult.baseline_rtt_ms,
            LatencyTestResult.rtt_under_load_ms,
            LatencyTestResult.rtt_p99_ms,
            LatencyTestResult.download_mbits_s,
            LatencyTestResult.upload_mbits_s,
        )
        .where(*conditions)
        .order_by(LatencyTestResult.start_timestamp)
    )

    rows = fetch_capped_rows(db, query, cap)

    return [LatencyRawLine(**row._asdict()) for row in rows]


def query_latency_public_points(
    db: Session,
    bbox: BoundingBox,
    metric: LatencyMetric,
    mission_type: str | None = None,
    campaign_id: int | None = None,
    cap: int | None = None,
) -> list[LatencyPublicLine]:
    """Public: individual results as start/end lines with metric values only -
    device_id, timestamps and test_type are never read from the database, and there is
    deliberately no device_id filter. Scoped to exactly one campaign like the public heatmap;
    same row cap and 400-on-overflow as `query_latency_raw`."""
    if cap is None:
        cap = RAW_ROW_CAP
    campaign = resolve_campaign(db, campaign_id)
    if campaign is None:
        return []
    metric_col = getattr(LatencyTestResult, metric.value)
    conditions = _row_conditions(metric_col, campaign.id, None, mission_type, bbox)

    query = (
        select(
            _START_LON.label("start_longitude"),
            _START_LAT.label("start_latitude"),
            _END_LON.label("end_longitude"),
            _END_LAT.label("end_latitude"),
            LatencyTestResult.baseline_rtt_ms,
            LatencyTestResult.rtt_under_load_ms,
            LatencyTestResult.rtt_p99_ms,
            LatencyTestResult.download_mbits_s,
            LatencyTestResult.upload_mbits_s,
        )
        .where(*conditions)
        .order_by(LatencyTestResult.start_timestamp)
    )

    return [LatencyPublicLine(**row._asdict()) for row in fetch_capped_rows(db, query, cap)]
