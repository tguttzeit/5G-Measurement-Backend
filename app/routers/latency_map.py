"""Router for the latency-result map endpoints: public heatmap/extent/points, and an
authenticated raw view.

Kept separate from `latency.py`, which is device-upload-only. Like `measurements.py`, routes are
registered without an `/api` prefix - the dev proxy and Caddy strip it before forwarding.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import current_active_user
from app.db import get_db
from app.latency_results_query import (
    query_latency_extent,
    query_latency_heatmap,
    query_latency_public_points,
    query_latency_raw,
)
from app.measurements_query import parse_bbox
from app.run_ids import RUN_ID_COLUMN_LENGTH
from app.schemas.latency_map import (
    GeoJSONLineGeometry,
    LatencyMetric,
    LatencyPublicPointFeature,
    LatencyPublicPointFeatureCollection,
    LatencyPublicPointProperties,
    LatencyRawFeature,
    LatencyRawFeatureCollection,
    LatencyRawProperties,
)
from app.schemas.measurement import (
    GeoJSONPointGeometry,
    HeatmapFeature,
    HeatmapFeatureCollection,
    HeatmapPointProperties,
    MeasurementExtent,
)

_BBOX = (
    "Bounding box `min_lon,min_lat,max_lon,max_lat`: longitude in [-180, 180], latitude in "
    "[-90, 90], min strictly less than max. 400 if malformed or out of range. Matched against "
    "the midpoint of a result's start and end position."
)
_METRIC = (
    "Latency metric: `baseline_rtt_ms`, `rtt_under_load_ms`, `rtt_p99_ms`, `download_mbits_s` "
    "or `upload_mbits_s`. Only results whose selected metric is non-null are returned."
)
_DEVICE_ID = "Only results of this device"
_MISSION_TYPE = (
    "Only results of this mission type (`ground`, `drone`), as stored on the result's run"
)
_PUBLIC_CAMPAIGN = (
    "Campaign to show. Defaults to the campaign with the most recent run end. 404 if it does "
    "not exist."
)

public_router = APIRouter(prefix="/latency-results", tags=["latency-map"])
authenticated_router = APIRouter(
    prefix="/latency-results", tags=["latency-map"], dependencies=[Depends(current_active_user)]
)


@public_router.get(
    "/extent",
    response_model=MeasurementExtent,
    summary="Bounding box of the matching latency results",
    description=(
        "Public, no authentication. The true bounding box `[min_lon, min_lat, max_lon, "
        "max_lat]` of the matching latency results, covering both ends of every matching row, "
        "or `null` if nothing matches. It takes no `bbox`. Rows with a placeholder GPS fix at "
        "either end are excluded. Campaign scoping is the same as for the heatmap."
    ),
)
def get_latency_extent(
    metric: LatencyMetric = Query(..., description=_METRIC),
    device_id: str | None = Query(None, description=_DEVICE_ID),
    mission_type: str | None = Query(None, description=_MISSION_TYPE),
    campaign_id: int | None = Query(None, description=_PUBLIC_CAMPAIGN),
    db: Session = Depends(get_db),
) -> MeasurementExtent:
    """Public, unauthenticated: the true bounding box of matching latency results, for fitting
    the map's initial view. Position-only, same campaign scoping as the heatmap."""
    extent = query_latency_extent(db, metric, device_id, mission_type, campaign_id)
    if extent is None:
        return MeasurementExtent(bbox=None)
    return MeasurementExtent(bbox=(extent.min_lon, extent.min_lat, extent.max_lon, extent.max_lat))


@public_router.get(
    "/heatmap",
    response_model=HeatmapFeatureCollection,
    summary="Latency heatmap points for the public map",
    description=(
        "Public, no authentication. Grid-averaged `value` and `count` at the cell center, in "
        "the same `FeatureCollection` shape as `GET /measurements/heatmap`. Each result has "
        "two positions (start and end); bounding box filtering and aggregation use their "
        "midpoint. Rows with a placeholder GPS fix at either end are excluded. Responses never "
        "carry device ids or timestamps. They are always scoped to exactly one campaign "
        "(`campaign_id`, by default the one with the most recent run end). Errors: 400 for a "
        "malformed `bbox`, 404 for an unknown `campaign_id`, 422 for an unknown `metric`."
    ),
)
def get_latency_heatmap(
    bbox: str = Query(..., description=_BBOX),
    metric: LatencyMetric = Query(..., description=_METRIC),
    device_id: str | None = Query(None, description=_DEVICE_ID),
    mission_type: str | None = Query(None, description=_MISSION_TYPE),
    campaign_id: int | None = Query(None, description=_PUBLIC_CAMPAIGN),
    db: Session = Depends(get_db),
) -> HeatmapFeatureCollection:
    """Public, unauthenticated: grid-averaged metric values positioned at each result's
    start/end midpoint. Never carries timestamps or device IDs, and is always scoped to exactly
    one campaign - there is no free-form date range."""
    grid = query_latency_heatmap(db, parse_bbox(bbox), metric, device_id, mission_type, campaign_id)
    return HeatmapFeatureCollection(
        features=[
            HeatmapFeature(
                geometry=GeoJSONPointGeometry(coordinates=(point.longitude, point.latitude)),
                properties=HeatmapPointProperties(value=point.value, count=point.count),
            )
            for point in grid.points
        ]
    )


@public_router.get(
    "/points",
    response_model=LatencyPublicPointFeatureCollection,
    summary="Individual latency results for the public map",
    description=(
        "Public, no authentication. A `FeatureCollection` of `LineString` features, one per "
        "latency result from its start to its end position, with only the five metric values "
        "as properties. The response has no `device_id`, timestamps, `test_type` or `run_id` "
        "field at all, and no `device_id` filter is accepted (it is ignored if sent). The "
        "campaign defaults like the heatmap. Rows with a placeholder GPS fix at either end are "
        "excluded. At most 5000 rows are returned to guests; more matches give 400, so zoom in "
        "or pick a campaign or filter. 404 for an unknown `campaign_id`."
    ),
)
def get_latency_points(
    bbox: str = Query(..., description=_BBOX),
    metric: LatencyMetric = Query(..., description=_METRIC),
    mission_type: str | None = Query(None, description=_MISSION_TYPE),
    campaign_id: int | None = Query(None, description=_PUBLIC_CAMPAIGN),
    db: Session = Depends(get_db),
) -> LatencyPublicPointFeatureCollection:
    """Public, unauthenticated: individual latency results as start-to-end lines with
    the five metric values, but never device_id, timestamps or test_type - the response schema has
    no field for them. No `device_id` filter, and the campaign defaults
    like the heatmap. 400 if the row cap is exceeded."""
    lines = query_latency_public_points(db, parse_bbox(bbox), metric, mission_type, campaign_id)
    return LatencyPublicPointFeatureCollection(
        features=[
            LatencyPublicPointFeature(
                geometry=GeoJSONLineGeometry(
                    coordinates=(
                        (line.start_longitude, line.start_latitude),
                        (line.end_longitude, line.end_latitude),
                    )
                ),
                properties=LatencyPublicPointProperties(
                    baseline_rtt_ms=line.baseline_rtt_ms,
                    rtt_under_load_ms=line.rtt_under_load_ms,
                    rtt_p99_ms=line.rtt_p99_ms,
                    download_mbits_s=line.download_mbits_s,
                    upload_mbits_s=line.upload_mbits_s,
                ),
            )
            for line in lines
        ]
    )


@authenticated_router.get(
    "/raw",
    response_model=LatencyRawFeatureCollection,
    summary="Detailed latency results for logged-in users",
    description=(
        "Requires a logged-in user (any account). A `FeatureCollection` of `LineString` "
        "features (`[[start_lon, start_lat], [end_lon, end_lat]]`) with `device_id`, "
        "`test_type`, `start_timestamp`, `end_timestamp` and all five metric values. By default "
        "there is no row cap; a superuser can set one with `PUT /settings/raw-row-cap`, and if "
        "more rows match than the cap the response is 400 rather than a truncated result. An "
        "omitted `campaign_id` means all time. The optional `run_id` restricts the result to "
        "one run. Errors: 400 for a malformed `bbox` or an exceeded row cap, 401 without a "
        "valid token, 404 for an unknown `campaign_id`."
    ),
)
def get_latency_raw(
    bbox: str = Query(..., description=_BBOX),
    metric: LatencyMetric = Query(..., description=_METRIC),
    device_id: str | None = Query(None, description=_DEVICE_ID),
    mission_type: str | None = Query(None, description=_MISSION_TYPE),
    campaign_id: int | None = Query(
        None,
        description="Campaign to show. Omit for all time: unlike the public endpoints this "
        "does not default to a campaign. 404 if it does not exist.",
    ),
    run_id: str | None = Query(
        None,
        max_length=RUN_ID_COLUMN_LENGTH,
        description="Only results of the run with this device-supplied id (at most 600 "
        "characters); combine it with `device_id` to select exactly one device's run",
    ),
    db: Session = Depends(get_db),
) -> LatencyRawFeatureCollection:
    """Authenticated (any logged-in user): individual latency results as start-to-end lines,
    each carrying all five metric values. Unlimited by default; 400 if a superuser-configured row
    cap is exceeded."""
    lines = query_latency_raw(
        db, parse_bbox(bbox), metric, device_id, mission_type, campaign_id, run_id=run_id
    )
    return LatencyRawFeatureCollection(
        features=[
            LatencyRawFeature(
                geometry=GeoJSONLineGeometry(
                    coordinates=(
                        (line.start_longitude, line.start_latitude),
                        (line.end_longitude, line.end_latitude),
                    )
                ),
                properties=LatencyRawProperties(
                    device_id=line.device_id,
                    test_type=line.test_type,
                    start_timestamp=line.start_timestamp,
                    end_timestamp=line.end_timestamp,
                    baseline_rtt_ms=line.baseline_rtt_ms,
                    rtt_under_load_ms=line.rtt_under_load_ms,
                    rtt_p99_ms=line.rtt_p99_ms,
                    download_mbits_s=line.download_mbits_s,
                    upload_mbits_s=line.upload_mbits_s,
                ),
            )
            for line in lines
        ]
    )
