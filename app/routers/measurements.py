"""Router for measurement data endpoints: device upload, and the public map/heatmap API.

The heatmap/export endpoints are deliberately unauthenticated, unlike every other
dashboard-facing route in this codebase.

Two separate `APIRouter`s: `router` (device upload) and `public_router` (heatmap/export).
Neither bakes `/api` into its own prefix - both the Vite dev proxy and the production Caddyfile's
`handle_path /api/*` strip that segment before forwarding, same as every other router in this
codebase (`testing`, `heartbeat`, ...), so routes must be registered without it to actually be
reachable through either proxy.
"""

import asyncio
import csv
import io
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import current_active_user, current_superuser, optional_active_user
from app.campaigns_query import list_campaigns
from app.db import get_db
from app.device_auth import verify_device_auth
from app.measurements_query import (
    parse_bbox,
    query_aggregated_points,
    query_extent,
    query_public_raw_points,
    query_raw_points,
    query_render_points,
    query_selection_export_points,
)
from app.models import Device
from app.models.measurement import Measurement
from app.models.user import User
from app.notifications import (
    NotificationChannel,
    deliver,
    get_notification_channel,
    prepare_notifications,
)
from app.run_ids import RUN_ID_COLUMN_LENGTH, legacy_run_id
from app.runs_store import upsert_runs
from app.schemas.campaign import CampaignListResponse
from app.schemas.datapoint import DatapointArray
from app.schemas.measurement import (
    ExportFormat,
    GeoJSONPointGeometry,
    HeatmapFeature,
    HeatmapFeatureCollection,
    HeatmapPointProperties,
    MeasurementExtent,
    Metric,
    PublicPointFeature,
    PublicPointFeatureCollection,
    PublicPointProperties,
    RawFeature,
    RawFeatureCollection,
    RawPointProperties,
    SelectionExportFeature,
    SelectionExportFeatureCollection,
    SelectionExportProperties,
    SelectionExportRequest,
    ViewMode,
)
from app.schemas.notifications import NotificationEvent
from app.upload_events import StreamLimitExceeded, Subscription, upload_broadcaster

_BBOX = (
    "Bounding box `min_lon,min_lat,max_lon,max_lat`: longitude in [-180, 180], latitude in "
    "[-90, 90], min strictly less than max. 400 if malformed or out of range."
)
_METRIC = "Cell quality metric: `rsrp`, `rsrq` or `sinr`"
_DEVICE_ID = "Only measurements of this device"
_MISSION_TYPE = (
    "Only measurements of this mission type (`ground`, `drone`). It is the mission type stored "
    "on the point's run, which a superuser can edit."
)
_PUBLIC_CAMPAIGN = (
    "Campaign to show. Defaults to the campaign with the most recent run end, so a caller never "
    "blends two campaigns into one point. 404 if it does not exist."
)

router = APIRouter(tags=["measurements"])
public_router = APIRouter(prefix="/measurements", tags=["measurements"])
# Every route on this router requires a logged-in user (not superuser-only - matches the
# MissionStatusPage/TestingVisualizationPage auth level) - richer map data for
# any authenticated user, not an admin-only tool.
authenticated_router = APIRouter(
    prefix="/measurements", tags=["measurements"], dependencies=[Depends(current_active_user)]
)


@router.post(
    "/measurements",
    status_code=status.HTTP_200_OK,
    summary="Upload measurement datapoints (device)",
    description=(
        "Device endpoint: the device authenticates with its `X-Device-ID` and `X-Device-Key` "
        "headers, which are checked before the request body is read. The body is a JSON array "
        "of datapoints, and every datapoint's `device_id` must be the authenticated device's "
        "(403 otherwise). Datapoints are stored in one transaction. Each datapoint's "
        "`run_id` assigns it to a run, which is created on first sight; datapoints without one "
        "belong to a synthetic `legacy-<device_id>-<mission_type>-<YYYY-MM-DD>` run. The "
        "attributes of an existing run are not overwritten by later uploads. Answers "
        "`{\"status\": \"success\", \"count\", \"device_id\"}`. 401 for missing or wrong "
        "device credentials, 422 for an invalid body."
    ),
)
async def upload_measurements(
    datapoints: DatapointArray,
    background_tasks: BackgroundTasks,
    device: Device = Depends(verify_device_auth),
    db: Session = Depends(get_db),
    channel: NotificationChannel = Depends(get_notification_channel),
) -> dict:
    """Receive and store measurement datapoints from device.

    Authenticated via X-Device-Key header with per-device lookup. Auth is a FastAPI
    dependency, so it runs before the (potentially large) request body is parsed.
    Accepts JSON array of Datapoint objects, validates against Pydantic model.
    One DB transaction per request: insert all datapoints, commit, respond.
    """
    # Check that all datapoints belong to the authenticated device
    for dp in datapoints.root:
        if dp.device_id != device.device_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Datapoint device_id {dp.device_id} does not match "
                    f"authenticated device {device.device_id}"
                ),
            )

    # Resolve every datapoint's run (created on first sight), then insert the measurements
    # attached to it, all in one transaction.
    datapoint_runs = [
        (dp, dp.run_id or legacy_run_id(dp.device_id, dp.mission_type, dp.timestamp))
        for dp in datapoints.root
    ]
    run_pks = upsert_runs(
        db, ((dp.device_id, run_id, dp.mission_type) for dp, run_id in datapoint_runs)
    )
    measurements = [
        Measurement(
            timestamp=dp.timestamp,
            device_id=dp.device_id,
            run_pk=run_pks[(dp.device_id, run_id)],
            latitude=dp.fix.position.latitude,
            longitude=dp.fix.position.longitude,
            placeholder=dp.fix.placeholder,
            rsrp=dp.cell_sample.rsrp,
            rsrq=dp.cell_sample.rsrq,
            sinr=dp.cell_sample.sinr,
            rat=dp.cell_sample.rat,
            raw_data=dp.model_dump(mode="json"),
        )
        for dp, run_id in datapoint_runs
    ]
    db.add_all(measurements)
    db.commit()

    if measurements:
        # Dedup while preserving first-seen order: a batch is almost always one run, but the
        # dashboard toast should list every run id if a device ever batches more than one.
        run_ids = list(dict.fromkeys(run_id for _, run_id in datapoint_runs))
        uploaded_at = datetime.now(UTC)
        upload_broadcaster.publish(device.device_id, run_ids, len(measurements), uploaded_at)
        prepared = prepare_notifications(
            db, [NotificationEvent.RUNS_UPLOADED], device.device_id, uploaded_at
        )
        if prepared:
            background_tasks.add_task(deliver, channel, prepared)

    return {
        "status": "success",
        "count": len(measurements),
        "device_id": device.device_id,
    }


# Idle gaps between uploads can run from minutes to hours (unlike heartbeats, roughly once a
# minute), so a keep-alive matters even more here to stop a proxy closing the idle connection.
_UPLOAD_KEEPALIVE_INTERVAL_S = 20


async def _upload_event_stream(
    subscription: Subscription, keepalive_s: float = _UPLOAD_KEEPALIVE_INTERVAL_S
) -> AsyncGenerator[str, None]:
    try:
        # Flushes the response headers right away so the client knows the stream is open.
        yield ": connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(subscription.queue.get(), timeout=keepalive_s)
            except TimeoutError:
                yield ": keep-alive\n\n"
            else:
                yield event.to_sse()
    finally:
        subscription.close()


@router.get(
    "/measurements/stream",
    response_class=StreamingResponse,
    summary="Stream a signal for each device upload, with the run ids just received",
    description=(
        "Server-Sent Events (`text/event-stream`), held open. Emits an `upload` event whenever "
        "any device's measurement upload is stored, so the dashboard can tell the user what "
        "just landed, for example after queuing `force-upload-now`:\n\n"
        "```\n: connected\n\nevent: upload\n"
        "data: {\"device_id\": \"5gmu_1\", "
        "\"run_ids\": [\"746841d6-bbdb-4dc3-bfc6-ac6153f37720\"], \"point_count\": 3, "
        "\"received_at\": \"2026-10-16T10:08:45+00:00\"}\n\n"
        ": keep-alive\n```\n\n"
        "Requires a superuser token, the same boundary as the remote command endpoints; device "
        "credentials are not accepted. The native `EventSource` cannot send the "
        "`Authorization` header, so clients use `fetch()` and read the response body as a "
        "stream; never put the token in the URL. Lines starting with `:` are comments: "
        "`: connected` is sent on open and `: keep-alive` after every 20 seconds of silence so "
        "proxies keep the idle connection open.\n\n"
        "`run_ids` lists every distinct run id of the uploaded batch in first-seen order "
        "(almost always one entry); a `null` entry means the batch's datapoints carried no "
        "explicit `run_id`. The stream is not scoped to one device: every subscriber hears "
        "about every device's uploads. If a subscriber's queue is full the oldest pending event "
        "is dropped to make room. Missed events are not replayed after a reconnect. Subscribers "
        "live in memory of one server process.\n\n"
        "Errors: 401 for a missing or invalid token, 403 for a non-superuser, 429 when the "
        "per-user (5) or global (100) limit of concurrent streams is reached."
    ),
)
async def stream_upload_events(
    user: User = Depends(current_superuser),
) -> StreamingResponse:
    try:
        subscription = upload_broadcaster.subscribe(user.id)
    except StreamLimitExceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many open streams"
        ) from None

    return StreamingResponse(
        _upload_event_stream(subscription),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@public_router.get(
    "/campaigns",
    response_model=CampaignListResponse,
    summary="List campaigns for the map's campaign picker",
    description=(
        "Public, no authentication. Campaign `id`, `name` and derived period only. `start` and "
        "`end` are the UTC days (`YYYY-MM-DD`) of the earliest and latest measurement over the "
        "campaign's runs, and `null` while it has none. No run ids, device ids or run counts. "
        "A campaign consists of the runs assigned to it."
    ),
)
def list_public_campaigns(db: Session = Depends(get_db)) -> CampaignListResponse:
    """Public, unauthenticated: campaign name/id/period labels only, for the map page's
    campaign picker. Safe to expose - no measurement data, no run or device identifiers."""
    return CampaignListResponse(campaigns=list_campaigns(db))


@public_router.get(
    "/extent",
    response_model=MeasurementExtent,
    summary="Bounding box of the matching measurements",
    description=(
        "Public, no authentication. The true minimum and maximum longitude and latitude of the "
        "measurements matching the filters, for example to fit the map's initial view. It takes "
        "no `bbox` and is not windowed to a viewport. Campaign scoping and the exclusion of "
        "placeholder GPS fixes are the same as for the heatmap; `bbox` is `null` if nothing "
        "matches."
    ),
)
def get_measurements_extent(
    metric: Metric = Query(..., description=_METRIC),
    device_id: str | None = Query(None, description=_DEVICE_ID),
    mission_type: str | None = Query(None, description=_MISSION_TYPE),
    campaign_id: int | None = Query(None, description=_PUBLIC_CAMPAIGN),
    db: Session = Depends(get_db),
) -> MeasurementExtent:
    """Public, unauthenticated: the real min/max lat/lon of rows matching the given filters.

    No bbox - this isn't windowed to a viewport, it's the true extent of the matching data,
    e.g. for fitting the map's initial view to it. Same campaign scoping and
    placeholder-exclusion as the heatmap endpoint; same position-only response shape.
    """
    extent = query_extent(db, metric, device_id, mission_type, campaign_id)
    if extent is None:
        return MeasurementExtent(bbox=None)
    return MeasurementExtent(
        bbox=(extent.min_lon, extent.min_lat, extent.max_lon, extent.max_lat)
    )


@public_router.get(
    "/heatmap",
    response_model=HeatmapFeatureCollection,
    summary="Heatmap points for the public map",
    description=(
        "Public, no authentication. A GeoJSON `FeatureCollection` of `Point`s with `value` (the "
        "requested metric) and `count` (rows behind the point). Below a row-count threshold "
        "within the bounding box the points are real individual measurements, lightly "
        "deduplicated; above it they are grid-aggregated cell averages, so the response size "
        "stays bounded however much data has accumulated. Responses never include timestamps, "
        "device ids or any other per-row metadata, only position and the metric. A response is "
        "always scoped to exactly one campaign (`campaign_id`, by default the one with the most "
        "recent run end), made of the runs assigned to it; measurements of runs in no campaign "
        "are never reachable here, and when no campaign has any run yet the response is empty. "
        "Errors: 400 for a malformed `bbox`, 404 for an unknown `campaign_id`."
    ),
)
def get_measurements_heatmap(
    bbox: str = Query(..., description=_BBOX),
    metric: Metric = Query(..., description=_METRIC),
    device_id: str | None = Query(None, description=_DEVICE_ID),
    mission_type: str | None = Query(None, description=_MISSION_TYPE),
    campaign_id: int | None = Query(None, description=_PUBLIC_CAMPAIGN),
    db: Session = Depends(get_db),
) -> HeatmapFeatureCollection:
    """Public, unauthenticated: adaptive (lat, lon, metric) points for the map page.

    Below a per-bbox row-count threshold, these are real individual measurements (lightly
    deduped); at/above it, grid-aggregated cells - see `query_render_points`. Either way, no
    auth - the response never carries timestamps, device IDs, or any other per-row metadata,
    only position and the requested metric's value. Always scoped to exactly one campaign -
    there is no free-form date-range param, so a caller can never blend two campaigns' data into
    one averaged point.
    """
    parsed_bbox = parse_bbox(bbox)
    grid = query_render_points(db, parsed_bbox, metric, device_id, mission_type, campaign_id)

    return HeatmapFeatureCollection(
        features=[
            HeatmapFeature(
                geometry=GeoJSONPointGeometry(coordinates=(point.longitude, point.latitude)),
                properties=HeatmapPointProperties(value=point.value, count=point.count),
            )
            for point in grid.points
        ],
    )


@public_router.get(
    "/points",
    response_model=PublicPointFeatureCollection,
    summary="Individual measurements for the public map",
    description=(
        "Public, no authentication. Individual measurements with exact position and all three "
        "metric values, for the map's Points display style. The response has no `device_id`, "
        "`timestamp`, `run_id` or raw data field at all; the measurement `id` is only there so "
        "a selection can be referenced by `POST /measurements/export-selection`. There is no "
        "`device_id` filter (an unknown query parameter is ignored). Rows with a placeholder "
        "GPS fix and rows whose selected `metric` is null are excluded. The campaign defaults "
        "like the heatmap. At most 5000 rows are returned to guests, regardless of the row cap "
        "setting of logged-in users; more matches give 400, so zoom in or pick a campaign or "
        "filter. 404 for an unknown `campaign_id`."
    ),
)
def get_measurements_points(
    bbox: str = Query(..., description=_BBOX),
    metric: Metric = Query(..., description=_METRIC),
    mission_type: str | None = Query(None, description=_MISSION_TYPE),
    campaign_id: int | None = Query(None, description=_PUBLIC_CAMPAIGN),
    db: Session = Depends(get_db),
) -> PublicPointFeatureCollection:
    """Public, unauthenticated: individual measurements with exact position and all
    three metric values, but never device_id, timestamp or any other per-row metadata - the
    response schema has no field for them. Unlike `/detailed`, there is no `device_id` filter
    (it would let a caller enumerate devices and their coverage), and the campaign defaults
    like the heatmap. 400 if the row cap is exceeded."""
    points = query_public_raw_points(db, parse_bbox(bbox), metric, mission_type, campaign_id)
    return PublicPointFeatureCollection(
        features=[
            PublicPointFeature(
                geometry=GeoJSONPointGeometry(coordinates=(point.longitude, point.latitude)),
                properties=PublicPointProperties(
                    id=point.id, rsrp=point.rsrp, rsrq=point.rsrq, sinr=point.sinr
                ),
            )
            for point in points
        ]
    )


@public_router.get(
    "/export",
    summary="Download the heatmap data as a file",
    description=(
        "Public, no authentication. The same filtered data as the heatmap, as a file download "
        "in `format` `csv` (columns `latitude`, `longitude`, the metric and `count`) or "
        "`geojson`. Errors are the same as for the heatmap."
    ),
)
def export_measurements(
    bbox: str = Query(..., description=_BBOX),
    metric: Metric = Query(..., description=_METRIC),
    format: ExportFormat = Query(
        ..., description="`csv` or `geojson`; PNG is a client-side capture of the rendered map"
    ),
    device_id: str | None = Query(None, description=_DEVICE_ID),
    mission_type: str | None = Query(None, description=_MISSION_TYPE),
    campaign_id: int | None = Query(None, description=_PUBLIC_CAMPAIGN),
    db: Session = Depends(get_db),
) -> Response:
    """Public, unauthenticated: same filtered/aggregated data as the heatmap, as a file download.

    PNG is not offered here - it's a client-side capture of the rendered map instead. Same
    campaign scoping as the heatmap endpoint - see its docstring.
    """
    parsed_bbox = parse_bbox(bbox)
    grid = query_render_points(db, parsed_bbox, metric, device_id, mission_type, campaign_id)

    if format == ExportFormat.CSV:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["latitude", "longitude", metric.value, "count"])
        for point in grid.points:
            writer.writerow([point.latitude, point.longitude, point.value, point.count])
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=measurements.csv"},
        )

    geojson = HeatmapFeatureCollection(
        features=[
            HeatmapFeature(
                geometry=GeoJSONPointGeometry(coordinates=(point.longitude, point.latitude)),
                properties=HeatmapPointProperties(value=point.value, count=point.count),
            )
            for point in grid.points
        ],
    )
    return Response(
        content=geojson.model_dump_json(),
        media_type="application/geo+json",
        headers={"Content-Disposition": "attachment; filename=measurements.geojson"},
    )


@public_router.post(
    "/export-selection",
    summary="Download selected map points as a file",
    description=(
        "Exports only the points selected in the map's Points style, as a file download. It is "
        "a POST because a selection can hold thousands of ids. No authentication is required; "
        "an `Authorization` header is optional and widens what resolves.\n\n"
        "Body (extra fields are rejected): `{\"ids\": [4711, 4712], \"format\": \"csv\"}`. "
        "`ids` is a non-empty list of positive integers, the `id` of the raw point features, "
        "deduplicated, with a server-side maximum of distinct ids (50000 by default). `format` "
        "is `csv` or `geojson`.\n\n"
        "Ids that do not exist, belong to placeholder fixes or are not visible to the caller "
        "are skipped silently, so the response cannot be used to probe for them. Guests only "
        "reach measurements of runs assigned to a campaign; logged-in users reach any "
        "measurement.\n\n"
        "The CSV has the columns `latitude`, `longitude`, `rsrp`, `rsrq`, `sinr`, "
        "`mission_type` and `campaign`; the GeoJSON `FeatureCollection` of `Point`s has the "
        "properties `rsrp`, `rsrq`, `sinr`, `mission_type` and `campaign`. `campaign` is the "
        "name of the campaign the point's run is assigned to (empty or `null` if none), and "
        "missing metric values are empty or `null`. Nothing else is exported: no `device_id`, "
        "`timestamp`, `run_id`, raw data or ids. Text cells in the CSV that start with `=`, "
        "`+`, `-`, `@`, a tab or a carriage return are prefixed with `'` against spreadsheet "
        "formula injection. 422 for an empty or oversized `ids`, non-positive or non-integer "
        "ids, an unknown `format` or unknown body fields; the message names only the violated "
        "constraint."
    ),
)
def export_selection(
    body: SelectionExportRequest,
    user: User | None = Depends(optional_active_user),
    db: Session = Depends(get_db),
) -> Response:
    """Public: export the selected map points as a file download. Only position,
    the three metrics, mission type and campaign name are returned - never device_id, timestamp,
    run_id, raw_data or the ids. Ids that do not exist or are not visible to the caller (guests
    only see measurements of runs assigned to a campaign, like the public map) are skipped
    silently, so the response cannot be used to probe for them."""
    points = query_selection_export_points(db, body.ids, include_unassigned=user is not None)

    if body.format == ExportFormat.CSV:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["latitude", "longitude", "rsrp", "rsrq", "sinr", "mission_type", "campaign"]
        )
        for point in points:
            writer.writerow(
                [
                    point.latitude,
                    point.longitude,
                    _csv_number(point.rsrp),
                    _csv_number(point.rsrq),
                    _csv_number(point.sinr),
                    _csv_text(point.mission_type),
                    _csv_text(point.campaign or ""),
                ]
            )
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=measurements-selection.csv"},
        )

    geojson = SelectionExportFeatureCollection(
        features=[
            SelectionExportFeature(
                geometry=GeoJSONPointGeometry(coordinates=(point.longitude, point.latitude)),
                properties=SelectionExportProperties(
                    rsrp=point.rsrp,
                    rsrq=point.rsrq,
                    sinr=point.sinr,
                    mission_type=point.mission_type,
                    campaign=point.campaign,
                ),
            )
            for point in points
        ]
    )
    return Response(
        content=geojson.model_dump_json(),
        media_type="application/geo+json",
        headers={"Content-Disposition": "attachment; filename=measurements-selection.geojson"},
    )


def _csv_number(value: float | None) -> float | str:
    return "" if value is None else value


def _csv_text(value: str) -> str:
    """Neutralize spreadsheet formula injection: a cell starting with one of these characters
    would be evaluated as a formula when the CSV is opened in a spreadsheet application."""
    return f"'{value}" if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


@authenticated_router.get(
    "/detailed",
    summary="Detailed map data for logged-in users",
    description=(
        "Requires a logged-in user (any account, not only superusers). A richer map view than "
        "the public heatmap, in two `view` modes.\n\n"
        "`aggregate` has the shape of the public heatmap: grid-aggregated `value` and `count` "
        "points, with a bounded response size. It is not restricted to one campaign: an omitted "
        "`campaign_id` means all time.\n\n"
        "`raw` returns one feature per matched measurement, with `id`, `device_id`, "
        "`timestamp`, position and all three metric columns together (`rsrp`, `rsrq`, `sinr`), "
        "not only the selected `metric`, so the Points style can show all three on click. There "
        "is no grid aggregation, so the response size follows the matched row count. By "
        "default there is no row cap; a superuser can set one with `PUT /settings/raw-row-cap`. "
        "With a cap set and exceeded, the response is 400 rather than a silently truncated "
        "result: zoom in, pick a campaign, filter by `device_id` or `mission_type`, or switch "
        "to `aggregate`.\n\n"
        "The uploaded raw payload is never included in any view. The optional `run_id` restricts "
        "the result to one run. Errors: 400 for a malformed `bbox` or an exceeded row cap, 401 "
        "without a valid token, 404 for an unknown `campaign_id`."
    ),
)
def get_measurements_detailed(
    bbox: str = Query(..., description=_BBOX),
    metric: Metric = Query(..., description=_METRIC),
    view: ViewMode = Query(..., description="`aggregate` or `raw`, see the endpoint description"),
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
        description="Only measurements of the run with this device-supplied id (at most 600 "
        "characters); combine it with `device_id` to select exactly one device's run",
    ),
    db: Session = Depends(get_db),
) -> HeatmapFeatureCollection | RawFeatureCollection:
    """Authenticated (any logged-in user, not superuser-only): a richer map view
    than the public heatmap, with two view modes.

    - `aggregate`: same shape/behavior as the public heatmap, but not restricted to a single
      campaign - `campaign_id` omitted means "all time" here, not a default campaign.
    - `raw`: individual measurement rows. Unlimited by default; if a superuser configured a row
      cap, it is enforced at the query level (see `query_raw_points`) and returns 400 when
      exceeded rather than silently truncating. Carries all three
      metric columns (not just the one selected for `metric`) so the Points display style can
      show every metric on click, not just whichever one colors the markers.

    `raw_data` (the full uploaded Datapoint blob) is never included in any view mode, regardless
    of auth - richer here means device_id/timestamp/metric columns, not the raw upload payload.
    """
    parsed_bbox = parse_bbox(bbox)

    if view == ViewMode.AGGREGATE:
        grid = query_aggregated_points(
            db,
            parsed_bbox,
            metric,
            device_id,
            mission_type,
            campaign_id,
            require_campaign=False,
            run_id=run_id,
        )
        return HeatmapFeatureCollection(
            features=[
                HeatmapFeature(
                    geometry=GeoJSONPointGeometry(coordinates=(point.longitude, point.latitude)),
                    properties=HeatmapPointProperties(value=point.value, count=point.count),
                )
                for point in grid.points
            ],
        )

    raw_points = query_raw_points(
        db, parsed_bbox, metric, device_id, mission_type, campaign_id, run_id=run_id
    )
    return RawFeatureCollection(
        features=[
            RawFeature(
                geometry=GeoJSONPointGeometry(coordinates=(point.longitude, point.latitude)),
                properties=RawPointProperties(
                    id=point.id,
                    device_id=point.device_id,
                    timestamp=point.timestamp,
                    rsrp=point.rsrp,
                    rsrq=point.rsrq,
                    sinr=point.sinr,
                ),
            )
            for point in raw_points
        ]
    )
