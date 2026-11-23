"""Shared bbox-filtered, grid-aggregated query for the heatmap and export endpoints.

Aggregation is always applied (not just above a size threshold), placeholder GPS rows are always
excluded, and the returned points never carry timestamp/device_id/other metadata - only position
and the requested metric's per-cell average. Aggregation is also always scoped to exactly one
campaign - never a free-form date range - so a public caller can never blend two campaigns'
data into one averaged point. A campaign's data is the measurements of the runs assigned to it
(`Run.campaign_id`); measurements of unassigned runs are never reachable through these queries
when a campaign is required.
"""

import math
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.app_settings import get_authenticated_raw_row_cap
from app.models.campaign import Campaign
from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from app.models.run import Run
from app.schemas.measurement import Metric

GRID_SIZE = 80

# Grid cells are anchored to this fixed global origin rather than to each query's own bbox
# - a bbox-relative grid reshuffles every cell's boundaries (and therefore its
# returned center/average) on every pan or resize, even though the underlying rows haven't
# changed. Anchoring to a fixed origin keeps a given point's cell identical across requests, as
# long as the zoom level (see _grid_cell_size below) doesn't change.
GRID_ORIGIN_LON = -180.0
GRID_ORIGIN_LAT = -90.0

# Cell size at zoom level 0 (the whole world in GRID_SIZE cells per axis); each subsequent level
# halves it, the same doubling-resolution-per-level idea as a map tile pyramid.
_BASE_CELL_LON = 360.0 / GRID_SIZE
_BASE_CELL_LAT = 180.0 / GRID_SIZE

# Sanity cap on how many times the cell size can halve - well past the point where cells are
# already finer than real GPS precision, just a guard against a degenerate (near-zero-span) bbox
# driving the level computation to an absurd value.
_MAX_ZOOM_LEVEL = 30


def _grid_cell_size(bbox: "BoundingBox") -> tuple[float, float]:
    """The (cell_lon, cell_lat) size for this bbox, picked from the fixed set of zoom levels
    (cell size halved each level, relative to GRID_ORIGIN_LON/LAT) rather than computed fresh
    from the bbox's own span.

    Picks the finest (most-zoomed-in) level whose grid still covers the bbox in at most
    GRID_SIZE cells per axis - the same response-size bound a bbox-relative grid gave, but from
    a fixed, pannable-without-reshuffling set of resolutions instead of one unique to this exact
    bbox. Misalignment between the bbox and the global grid can add at most one extra cell on
    each edge, so the true worst case is (GRID_SIZE + 1)**2 cells, not unbounded.
    """
    lon_span = bbox.max_lon - bbox.min_lon
    lat_span = bbox.max_lat - bbox.min_lat
    lon_level = math.floor(math.log2(GRID_SIZE * _BASE_CELL_LON / lon_span))
    lat_level = math.floor(math.log2(GRID_SIZE * _BASE_CELL_LAT / lat_span))
    level = max(0, min(lon_level, lat_level, _MAX_ZOOM_LEVEL))

    return _BASE_CELL_LON / 2**level, _BASE_CELL_LAT / 2**level

# Rendering-mode threshold: below this many matching rows in the bbox,
# `query_render_points` returns real individual points (after a small fixed-radius dedup, see
# DEDUP_RADIUS_METERS) so the map renders through the heat layer the same way the authenticated
# raw view looks - at or above it, falls back to the adaptive grid aggregation so response size
# (and client render cost) stays capped regardless of how much data has accumulated in the area.
# Expected to need tuning against real field data.
POINT_RENDER_THRESHOLD = 2000

# Points within this distance of each other are merged into one even in "real points" mode -
# handles near-duplicate GPS pings at virtually the same spot (e.g. a device stopped briefly)
# that would otherwise stack up and visually overdrive the heat layer's additive blending right
# there. Not real clustering, just de-duplication - see POINT_RENDER_THRESHOLD for where the grid
# aggregation (actual clustering) takes over.
DEDUP_RADIUS_METERS = 2.5

_METERS_PER_DEGREE_LATITUDE = 111_320.0

# Fixed reference latitude for converting DEDUP_RADIUS_METERS to a degrees-longitude cell size
# (degrees-latitude doesn't depend on latitude at all). Deliberately NOT the viewport bbox's own
# center latitude - that would make the dedup cell size (and therefore cell boundaries) shift
# slightly with every pan/zoom, undermining the pan-stability the zoom-bucketed
# main grid provides. A fixed reference is a close-enough approximation for this deployment's
# real-world latitude range; it only affects dedup precision, not correctness.
_DEDUP_REFERENCE_LATITUDE = 50.0


def _meters_to_degrees(meters: float, latitude: float) -> tuple[float, float]:
    """Approximate (degrees_lon, degrees_lat) for a distance in meters at the given latitude -
    accurate enough for a small dedup radius, not meant for anything precision-sensitive."""
    degrees_lat = meters / _METERS_PER_DEGREE_LATITUDE
    degrees_lon = meters / (_METERS_PER_DEGREE_LATITUDE * math.cos(math.radians(latitude)))
    return degrees_lon, degrees_lat


# Guests' hard, query-level raw row cap (see query_public_raw_points) - large enough to be usable
# for a single narrowed-down bbox/campaign query, small enough to keep the response payload
# reasonable to transfer and render client-side. Logged-in users' cap is a superuser-editable
# setting instead (see `app.app_settings`), unlimited by default.
RAW_ROW_CAP = 5000

@dataclass(frozen=True)
class BoundingBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


@dataclass(frozen=True)
class AggregatedPoint:
    latitude: float
    longitude: float
    value: float
    count: int


@dataclass(frozen=True)
class AggregatedGrid:
    """`query_aggregated_points`'s result: the occupied cells plus the shared cell size every
    one of them was computed with - callers that render cells as filled areas need
    the size to draw them, not just each cell's center."""

    cell_width: float
    cell_height: float
    points: list[AggregatedPoint]


@dataclass(frozen=True)
class Extent:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


@dataclass(frozen=True)
class RawPoint:
    id: int
    latitude: float
    longitude: float
    device_id: str
    timestamp: datetime
    rsrp: float | None
    rsrq: float | None
    sinr: float | None


@dataclass(frozen=True)
class PublicRawPoint:
    id: int
    latitude: float
    longitude: float
    rsrp: float | None
    rsrq: float | None
    sinr: float | None


@dataclass(frozen=True)
class SelectionExportPoint:
    latitude: float
    longitude: float
    rsrp: float | None
    rsrq: float | None
    sinr: float | None
    mission_type: str
    campaign: str | None


def parse_bbox(bbox: str) -> BoundingBox:
    """Parse and validate a `min_lon,min_lat,max_lon,max_lat` bbox string.

    Raises HTTPException(400) on anything malformed rather than letting a bad bbox reach the
    query layer - this is a public endpoint, so input validation happens before any DB work.
    """
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="bbox must be 'min_lon,min_lat,max_lon,max_lat'",
        )

    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="bbox values must be numbers",
        )

    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="longitude must be between -180 and 180"
        )
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="latitude must be between -90 and 90"
        )
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="bbox min values must be strictly less than max values",
        )

    return BoundingBox(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)


def resolve_campaign(db: Session, campaign_id: int | None) -> Campaign | None:
    """Resolve the campaign to scope aggregation to.

    An explicit `campaign_id` must resolve to an existing campaign - raises 404 otherwise, since
    that's a caller error (stale/typo'd id), not a "no campaigns configured yet" state.

    With no `campaign_id`, defaults to the campaign with the most recent run end (the newest
    measurement timestamp among its runs that are not in the trash). Returns None when no
    campaign has any such run yet, so a public caller gets an empty result rather than data that
    belongs to no campaign.
    """
    if campaign_id is not None:
        campaign = db.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
            )
        return campaign

    most_recent_campaign_id = db.scalar(
        select(Run.campaign_id)
        .join(Measurement, Measurement.run_pk == Run.id)
        .where(Run.campaign_id.isnot(None), Run.deleted_at.is_(None))
        .group_by(Run.campaign_id)
        .order_by(func.max(Measurement.timestamp).desc(), Run.campaign_id.desc())
        .limit(1)
    )
    if most_recent_campaign_id is None:
        return None
    return db.get(Campaign, most_recent_campaign_id)


def resolve_optional_campaign_id(db: Session, campaign_id: int | None) -> int | None:
    """Authenticated "any campaign, or all time" resolution, distinct from
    `resolve_campaign`'s public-caller default: here `None` means no campaign scoping at all
    (all time), not "pick the most recent campaign" - logged-in callers are trusted to pick
    their own scope rather than needing a sensible default for a first-time visitor.

    An explicit `campaign_id` still must resolve to an existing campaign, same as
    `resolve_campaign` - raises 404 otherwise.
    """
    if campaign_id is None:
        return None

    if db.get(Campaign, campaign_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return campaign_id


def run_filter(
    model: type[Measurement] | type[LatencyTestResult],
    campaign_id: int | None = None,
    mission_type: str | None = None,
    run_id: str | None = None,
) -> ColumnElement[bool]:
    """Condition selecting the rows of `model` whose run is not in the trash and matches all the
    given run attributes (`run_id` is the device-supplied one). Rows reach their campaign and
    mission type through their run, so a single semi-join covers all of them."""
    run_conditions = [Run.deleted_at.is_(None)]
    if campaign_id is not None:
        run_conditions.append(Run.campaign_id == campaign_id)
    if mission_type is not None:
        run_conditions.append(Run.mission_type == mission_type)
    if run_id is not None:
        run_conditions.append(Run.run_id == run_id)
    return model.run_pk.in_(select(Run.id).where(*run_conditions))


def query_aggregated_points(
    db: Session,
    bbox: BoundingBox,
    metric: Metric,
    device_id: str | None = None,
    mission_type: str | None = None,
    campaign_id: int | None = None,
    require_campaign: bool = True,
    run_id: str | None = None,
) -> AggregatedGrid:
    """Bbox-filtered measurements, aggregated into a fixed grid and averaged per cell.

    One point per occupied grid cell, at the cell's center - bounds response size to at most
    roughly GRID_SIZE**2 points regardless of how many rows fall in the bbox (see
    `_grid_cell_size`). The grid itself is anchored to a fixed global origin, not to this bbox
    - a point's cell only changes when the zoom level does, not on every pan/resize.

    Adjacent cells are deliberately NOT merged into blobs - an earlier version of this did that,
    but for spatially continuous/dense data (the common case once a campaign has enough rows to
    reach this code path at all) nearly every occupied cell ends up touching its neighbors, so
    transitive merging collapsed almost the whole bbox into one or two giant blobs instead of a
    useful number of distinct points. That merge step existed to avoid a blocky
    chopped-into-rows look under the rectangle-per-cell rendering this project used briefly: with
    the current heat-blur rendering, nearby grid points already blend together visually on their
    own, so there's nothing left for cell-merging to buy.

    `require_campaign` (default True, the public-caller behavior) always scopes to exactly one
    campaign's runs (see `resolve_campaign`), defaulting to the campaign with the most recent run
    end when `campaign_id` is omitted - never a caller-supplied free-form range. Authenticated
    callers pass `require_campaign=False`, under which an omitted `campaign_id` means
    "all time" instead of a default campaign - see `resolve_optional_campaign_id`. `run_id`
    is likewise authenticated-only: the public query functions never take it.
    """
    if require_campaign:
        campaign = resolve_campaign(db, campaign_id)
        if campaign is None:
            # No campaigns configured yet: nothing is "in" any campaign, so nothing is public yet.
            cell_width, cell_height = _grid_cell_size(bbox)
            return AggregatedGrid(cell_width=cell_width, cell_height=cell_height, points=[])
        scoped_campaign_id = campaign.id
    else:
        scoped_campaign_id = resolve_optional_campaign_id(db, campaign_id)

    metric_col = getattr(Measurement, metric.value)
    cell_width, cell_height = _grid_cell_size(bbox)
    return _aggregate_with_cell_size(
        db,
        bbox,
        metric_col,
        scoped_campaign_id,
        device_id,
        mission_type,
        cell_width,
        cell_height,
        run_id,
    )


def _aggregate_with_cell_size(
    db: Session,
    bbox: BoundingBox,
    metric_col,
    campaign_id: int | None,
    device_id: str | None,
    mission_type: str | None,
    cell_width: float,
    cell_height: float,
    run_id: str | None = None,
) -> AggregatedGrid:
    """Grid-aggregate the matching rows using the given cell size - shared by
    `query_aggregated_points` (adaptive, viewport-sized cells) and `query_render_points`'s dedup
    path (fixed, ~DEDUP_RADIUS_METERS cells)."""
    conditions = _row_conditions(bbox, metric_col, campaign_id, device_id, mission_type, run_id)
    cell_x = func.floor((Measurement.longitude - GRID_ORIGIN_LON) / cell_width)
    cell_y = func.floor((Measurement.latitude - GRID_ORIGIN_LAT) / cell_height)

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

    cells = [
        (int(row.cell_x), int(row.cell_y), row.avg_value, row.point_count)
        for row in db.execute(query)
    ]

    return AggregatedGrid(
        cell_width=cell_width,
        cell_height=cell_height,
        points=[
            AggregatedPoint(
                longitude=GRID_ORIGIN_LON + (cell_x + 0.5) * cell_width,
                latitude=GRID_ORIGIN_LAT + (cell_y + 0.5) * cell_height,
                value=value,
                count=count,
            )
            for cell_x, cell_y, value, count in cells
        ],
    )


def query_render_points(
    db: Session,
    bbox: BoundingBox,
    metric: Metric,
    device_id: str | None = None,
    mission_type: str | None = None,
    campaign_id: int | None = None,
) -> AggregatedGrid:
    """Adaptive rendering data for the public map.

    Below `POINT_RENDER_THRESHOLD` matching rows in the bbox: real individual points, deduped
    within `DEDUP_RADIUS_METERS` of each other, so the heat layer renders the actual data - the
    same visual the authenticated raw view already has. At or above the threshold: falls back to
    the same bounded grid aggregation `query_aggregated_points` uses, so response size (and
    client render cost) stays capped regardless of how much data has accumulated in the area -
    the raw view's hard row cap would otherwise just 400 instead.

    Public-caller only - always scoped to exactly one campaign, same as `query_aggregated_points`
    with `require_campaign=True` (see `resolve_campaign`).
    """
    campaign = resolve_campaign(db, campaign_id)
    if campaign is None:
        cell_width, cell_height = _grid_cell_size(bbox)
        return AggregatedGrid(cell_width=cell_width, cell_height=cell_height, points=[])

    metric_col = getattr(Measurement, metric.value)
    conditions = _row_conditions(bbox, metric_col, campaign.id, device_id, mission_type)
    count = db.scalar(select(func.count(Measurement.id)).where(*conditions))

    if count is not None and count > POINT_RENDER_THRESHOLD:
        cell_width, cell_height = _grid_cell_size(bbox)
    else:
        cell_width, cell_height = _meters_to_degrees(DEDUP_RADIUS_METERS, _DEDUP_REFERENCE_LATITUDE)

    return _aggregate_with_cell_size(
        db, bbox, metric_col, campaign.id, device_id, mission_type, cell_width, cell_height
    )


def query_extent(
    db: Session,
    metric: Metric,
    device_id: str | None = None,
    mission_type: str | None = None,
    campaign_id: int | None = None,
) -> Extent | None:
    """The real min/max lat/lon of rows matching the given filters - no bbox/grid involved.

    Unlike `query_aggregated_points`, this isn't windowed to a viewport: the caller wants to know
    where the data actually is (e.g. to fit the initial map view to it), not a grid-aggregated
    rendering of one bbox. A grid cell's center can sit well away from the real data inside that
    cell - this sidesteps that entirely by reading the true extent straight from the
    rows.

    Same public-caller campaign default as `query_aggregated_points` (the campaign with the most
    recent run end when `campaign_id` is omitted). Returns `None` when no campaign has runs yet, or
    no row matches the filters.
    """
    campaign = resolve_campaign(db, campaign_id)
    if campaign is None:
        return None

    metric_col = getattr(Measurement, metric.value)
    conditions = [
        Measurement.placeholder.is_(False),
        metric_col.isnot(None),
        run_filter(Measurement, campaign.id, mission_type),
    ]
    if device_id is not None:
        conditions.append(Measurement.device_id == device_id)

    row = db.execute(
        select(
            func.min(Measurement.longitude),
            func.min(Measurement.latitude),
            func.max(Measurement.longitude),
            func.max(Measurement.latitude),
        ).where(*conditions)
    ).one()
    min_lon, min_lat, max_lon, max_lat = row
    if min_lon is None:
        return None

    return Extent(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)


def _row_conditions(
    bbox: BoundingBox,
    metric_col,
    campaign_id: int | None,
    device_id: str | None,
    mission_type: str | None,
    run_id: str | None = None,
) -> list:
    """Shared bbox/campaign/device/mission_type/run WHERE conditions for the raw authenticated query
    mode - same filtering as `query_aggregated_points`, factored out since it needs the same
    conditions without the grid-cell aggregation."""
    conditions = [
        Measurement.longitude >= bbox.min_lon,
        Measurement.longitude <= bbox.max_lon,
        Measurement.latitude >= bbox.min_lat,
        Measurement.latitude <= bbox.max_lat,
        Measurement.placeholder.is_(False),
        metric_col.isnot(None),
    ]
    conditions.append(run_filter(Measurement, campaign_id, mission_type, run_id))
    if device_id is not None:
        conditions.append(Measurement.device_id == device_id)
    return conditions


def query_raw_points(
    db: Session,
    bbox: BoundingBox,
    metric: Metric,
    device_id: str | None = None,
    mission_type: str | None = None,
    campaign_id: int | None = None,
    cap: int | None = None,
    run_id: str | None = None,
) -> list[RawPoint]:
    """Authenticated: individual, ungrouped `Measurement` rows within the bbox/
    filters - device_id/timestamp/position/the requested metric only, never `raw_data`.

    `cap` defaults to the superuser-configured authenticated row cap (see `app.app_settings`),
    where no stored value means unlimited. When a cap applies it is enforced at the query level
    via `LIMIT cap + 1`: fetches one row past the cap to detect overflow without ever pulling an
    unbounded result set into memory, and raises 400 rather than silently truncating - unlike the
    aggregated modes, raw mode has no grid-aggregation bound on output size, and this endpoint
    allows an unrestricted "all time" range with no campaign scoping required.
    """
    if cap is None:
        cap = get_authenticated_raw_row_cap(db)
    scoped_campaign_id = resolve_optional_campaign_id(db, campaign_id)
    metric_col = getattr(Measurement, metric.value)
    conditions = _row_conditions(
        bbox, metric_col, scoped_campaign_id, device_id, mission_type, run_id
    )

    query = (
        select(
            Measurement.id,
            Measurement.device_id,
            Measurement.timestamp,
            Measurement.latitude,
            Measurement.longitude,
            Measurement.rsrp,
            Measurement.rsrq,
            Measurement.sinr,
        )
        .where(*conditions)
        .order_by(Measurement.timestamp)
    )

    rows = fetch_capped_rows(db, query, cap)

    return [
        RawPoint(
            id=row.id,
            longitude=row.longitude,
            latitude=row.latitude,
            device_id=row.device_id,
            timestamp=row.timestamp,
            rsrp=row.rsrp,
            rsrq=row.rsrq,
            sinr=row.sinr,
        )
        for row in rows
    ]


def fetch_capped_rows(db: Session, query, cap: int | None) -> list:
    """Run `query` limited to `cap + 1` rows and raise 400 on overflow rather than silently
    truncating, so a capped raw view never pulls an unbounded result set. `cap=None` means
    unlimited: the query runs as given."""
    if cap is None:
        return db.execute(query).all()

    rows = db.execute(query.limit(cap + 1)).all()
    if len(rows) > cap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Too many raw points in this viewing scope in raw view mode. Zoom in or try a "
                "campaign or filter setting that reduces shown datapoints."
            ),
        )
    return rows


def query_public_raw_points(
    db: Session,
    bbox: BoundingBox,
    metric: Metric,
    mission_type: str | None = None,
    campaign_id: int | None = None,
    cap: int | None = None,
) -> list[PublicRawPoint]:
    """Public: individual `Measurement` rows within the bbox, selecting only
    position and the three metric columns - device_id and timestamp are never read from the
    database, and there is deliberately no device_id filter. Scoped to exactly one campaign like
    the public heatmap (see `resolve_campaign`); same row cap and 400-on-overflow as
    `query_raw_points`."""
    if cap is None:
        cap = RAW_ROW_CAP
    campaign = resolve_campaign(db, campaign_id)
    if campaign is None:
        return []
    metric_col = getattr(Measurement, metric.value)
    conditions = _row_conditions(bbox, metric_col, campaign.id, None, mission_type)

    query = (
        select(
            Measurement.id,
            Measurement.latitude,
            Measurement.longitude,
            Measurement.rsrp,
            Measurement.rsrq,
            Measurement.sinr,
        )
        .where(*conditions)
        .order_by(Measurement.timestamp)
    )

    return [
        PublicRawPoint(
            id=row.id,
            latitude=row.latitude,
            longitude=row.longitude,
            rsrp=row.rsrp,
            rsrq=row.rsrq,
            sinr=row.sinr,
        )
        for row in fetch_capped_rows(db, query, cap)
    ]


def query_selection_export_points(
    db: Session, ids: list[int], include_unassigned: bool
) -> list[SelectionExportPoint]:
    """The given measurements with only what a selection export may carry (position,
    metrics, mission type, campaign name). Ids that do not exist, are placeholders, or are not
    visible to the caller are skipped without distinction. Guests (`include_unassigned=False`)
    only reach measurements of runs assigned to a campaign, like the public map."""
    query = (
        select(
            Measurement.latitude,
            Measurement.longitude,
            Measurement.rsrp,
            Measurement.rsrq,
            Measurement.sinr,
            Run.mission_type,
            Campaign.name.label("campaign"),
        )
        .select_from(Measurement)
        .join(Run, Run.id == Measurement.run_pk)
        .outerjoin(Campaign, Campaign.id == Run.campaign_id)
        .where(
            Measurement.id.in_(ids),
            Measurement.placeholder.is_(False),
            Measurement.latitude.isnot(None),
            Measurement.longitude.isnot(None),
            Run.deleted_at.is_(None),
        )
        .order_by(Measurement.id)
    )
    if not include_unassigned:
        query = query.where(Run.campaign_id.isnot(None))

    return [
        SelectionExportPoint(
            latitude=row.latitude,
            longitude=row.longitude,
            rsrp=row.rsrp,
            rsrq=row.rsrq,
            sinr=row.sinr,
            mission_type=row.mission_type,
            campaign=row.campaign,
        )
        for row in db.execute(query)
    ]
