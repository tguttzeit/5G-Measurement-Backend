"""Device listing API, powering the Remote Configuration page's device dropdown and the
Mission Status page's device selector. Open to any authenticated user:
the queuing endpoints in app/routers/commands.py keep their own superuser gate, so seeing a
device here grants no ability to act on it.
"""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import current_active_user
from app.db import get_db
from app.models import Device, Heartbeat
from app.models.user import User
from app.schemas.device import DeviceListResponse, DeviceSummary

router = APIRouter(prefix="/devices", tags=["devices"])

# Devices heartbeat every 60s by default. A device is considered
# online if it's been heard from within a few missed intervals, not just the last one, so a
# single delayed heartbeat doesn't flip it to "offline" in the dropdown.
ONLINE_THRESHOLD = timedelta(seconds=300)


@router.get(
    "",
    response_model=DeviceListResponse,
    summary="List registered devices",
    description=(
        "Requires a logged-in user (any account); seeing a device here grants no ability to "
        "act on it. Every registered device, ordered by id, with `online` and "
        "`last_heartbeat_at`. A device is online if it was heard from within the last 5 "
        "minutes, so a single delayed heartbeat does not flip it to offline. 401 without a "
        "valid token."
    ),
)
async def list_devices(
    db: Session = Depends(get_db),
    _: User = Depends(current_active_user),
) -> DeviceListResponse:
    latest_subquery = (
        select(
            Heartbeat.device_id,
            func.max(Heartbeat.received_at).label("latest_received_at"),
        )
        .group_by(Heartbeat.device_id)
        .subquery()
    )
    latest_by_device = dict(
        db.execute(select(latest_subquery.c.device_id, latest_subquery.c.latest_received_at)).all()
    )

    now = datetime.now(UTC)
    devices = db.scalars(select(Device).order_by(Device.device_id)).all()

    summaries = []
    for device in devices:
        last_heartbeat = latest_by_device.get(device.device_id)
        online = (
            last_heartbeat is not None
            and now - last_heartbeat.replace(tzinfo=UTC) < ONLINE_THRESHOLD
        )
        summaries.append(
            DeviceSummary(
                device_id=device.device_id,
                online=online,
                last_heartbeat_at=last_heartbeat.isoformat() if last_heartbeat else None,
            )
        )

    return DeviceListResponse(devices=summaries)
