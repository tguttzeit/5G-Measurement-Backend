"""Live GPS-fix-finding diagnostic endpoints.

Companion to `run-gps-fix-test-now`/`stop-gps-fix-test-now` (app/schemas/commands.py), queued
via app/routers/commands.py and delivered on the device's next heartbeat like every other
one-shot command. While that run is going, the device pushes its live status here directly,
bypassing the heartbeat channel entirely - the heartbeat's default 60s cadence is far too slow
for a live view, and this is a short burst of high-frequency updates, not the kind of
general-purpose status/command traffic the heartbeat channel is built for.

Only the latest report per device is kept - no historical time series, matching the
"live-only" scope of the feature (see the GpsFixTestStatus model).
"""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import current_superuser
from app.db import get_db
from app.device_auth import verify_device_auth
from app.models import Device, GpsFixTestStatus
from app.models.user import User
from app.schemas import ApiResponse, GpsFixTestStatusCreate, GpsFixTestStatusResponse

router = APIRouter(prefix="/devices/{device_id}", tags=["gps-fix-test"])

# The device's own default report_interval_s (measurement_software's [gps_fix_test] config
# section) is 2s; a report is considered stale - and the run treated as no-longer-active - once
# it's been more than 3 missed intervals since the last one, mirroring devices.py's
# ONLINE_THRESHOLD reasoning for heartbeats. This is a fixed default rather than something read
# from the device's actual configured interval, since the backend has no visibility into that.
_DEFAULT_REPORT_INTERVAL_S = 2.0
STALE_AFTER = timedelta(seconds=_DEFAULT_REPORT_INTERVAL_S * 3)


def _get_device_or_404(device_id: str, db: Session) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown device '{device_id}'",
        )
    return device


@router.post(
    "/gps-fix-test/status",
    response_model=ApiResponse,
    summary="Push a live gps-fix-test status report",
    description=(
        "Device endpoint: while a GPS-fix test is running (`run-gps-fix-test-now`), the device "
        "pushes its live status here, at a much higher rate than the heartbeat allows. The "
        "device authenticates with its `X-Device-ID` and `X-Device-Key` headers, and the "
        "`device_id` in the path must be the authenticated device's (403 otherwise). Body: "
        "`num_satellites` (0 to 64), `has_fix` and `elapsed_s` (0 to 86400). Only the latest "
        "report is kept: each push replaces the previous one."
    ),
)
async def push_gps_fix_test_status(
    device_id: str,
    payload: GpsFixTestStatusCreate,
    device: Device = Depends(verify_device_auth),
    db: Session = Depends(get_db),
) -> ApiResponse:
    if device_id != device.device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"path device_id '{device_id}' does not match "
                f"authenticated device '{device.device_id}'"
            ),
        )

    row = db.get(GpsFixTestStatus, device_id)
    if row is None:
        row = GpsFixTestStatus(device_id=device_id)
        db.add(row)

    row.num_satellites = payload.num_satellites
    row.has_fix = payload.has_fix
    row.elapsed_s = payload.elapsed_s
    row.updated_at = datetime.now(UTC)

    db.commit()

    return ApiResponse(status="ok", message="gps-fix-test status received")


@router.get(
    "/gps-fix-test/status",
    response_model=GpsFixTestStatusResponse,
    summary="Get the live gps-fix-test status for a device",
    description=(
        "Superuser only. The latest GPS-fix test status of a device, for the Find GPS Fix "
        "page. `run_active` is `false`, with no other field populated, when no report was ever "
        "received or the last one is older than 6 seconds, so a frozen count is not shown as "
        "live. Otherwise it is `true` with `num_satellites`, `has_fix`, `elapsed_s` and "
        "`updated_at`. 401 without a valid token, 403 for a non-superuser, 404 for an unknown "
        "device."
    ),
)
async def get_gps_fix_test_status(
    device_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(current_superuser),
) -> GpsFixTestStatusResponse:
    _get_device_or_404(device_id, db)

    row = db.get(GpsFixTestStatus, device_id)
    if row is None or datetime.now(UTC) - row.updated_at.replace(tzinfo=UTC) > STALE_AFTER:
        return GpsFixTestStatusResponse(run_active=False)

    return GpsFixTestStatusResponse(
        run_active=True,
        num_satellites=row.num_satellites,
        has_fix=row.has_fix,
        elapsed_s=row.elapsed_s,
        updated_at=row.updated_at.isoformat(),
    )
