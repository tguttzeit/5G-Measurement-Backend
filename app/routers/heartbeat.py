"""Heartbeat ingestion and retrieval endpoints."""
import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.app_settings import get_shutdown_confirmation
from app.auth import current_active_user
from app.command_events import command_ack_broadcaster
from app.command_status import (
    RECEIVED_IS_TERMINAL_FOR,
    confirm_shutdowns,
    device_heartbeat_interval_s,
    fail_unresponsive_shutdowns,
    record_reported_shutdown_successes,
)
from app.db import get_db
from app.device_auth import verify_device_auth
from app.heartbeat_events import StreamLimitExceeded, Subscription, heartbeat_broadcaster
from app.models import (
    CommandLogDirection,
    CommandLogEntry,
    CommandType,
    Device,
    DeviceCommand,
    Heartbeat,
)
from app.models.user import User
from app.notifications import (
    NotificationChannel,
    deliver,
    detect_heartbeat_events,
    get_notification_channel,
    prepare_notifications,
)
from app.response_signing import sign_heartbeat_response
from app.schemas import (
    DeviceHeartbeatSummary,
    HeartbeatListResponse,
    HeartbeatPayload,
    HeartbeatResponse,
)
from app.schemas.commands import ConfigOverrideCreate, OneShotCommand

# Every status the device is currently known to send. "not_applicable" (added device-side
# without warning - the precondition for the command wasn't met, e.g. sim-reset-now with no
# active measurement) is terminal like success/failed: nothing about redelivering it again
# would change that outcome. Anything outside this set is logged and left queued rather than
# treated as either outcome, so a future status we don't know about yet degrades gracefully
# instead of 422ing every heartbeat the device ever sends again (what happened here).
_TERMINAL_STATUSES = {"success", "failed", "not_applicable"}
_KNOWN_STATUSES = _TERMINAL_STATUSES | {"received"}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/heartbeat", tags=["heartbeat"])

# Defense in depth: even if a disallowed field ended up persisted some other way, only
# fields declared on the write-time schema are ever read back out into a response.
_ALLOWED_OVERRIDE_FIELDS = set(ConfigOverrideCreate.model_fields)

# `current_config` is an unvalidated free-form dict (unlike every other heartbeat field, which
# is a typed scalar) - cap its size so a misbehaving/compromised device can't send an
# arbitrarily large blob per heartbeat.
_MAX_CURRENT_CONFIG_BYTES = 4096

# Devices heartbeat roughly once a minute, so an idle stream would otherwise sit silent long
# enough for a proxy to close it. A comment line is ignored by SSE clients.
_KEEPALIVE_INTERVAL_S = 20


def reported_system_mode(current_config: dict | None) -> str | None:
    """The device mode for callers who can't read `current_config`; `mode` is what older device
    builds report instead of `system_mode`."""
    if not current_config:
        return None
    mode = current_config.get("system_mode", current_config.get("mode"))
    return mode if mode in ("manual", "auto") else None


def _override_is_applied(row: DeviceCommand, current_config: dict | None) -> bool:
    if not current_config or row.field not in current_config:
        return False
    wanted, reported = row.payload["value"], current_config[row.field]
    if isinstance(wanted, bool) or isinstance(reported, bool):
        return type(wanted) is type(reported) and wanted == reported
    if isinstance(wanted, (int, float)) and isinstance(reported, (int, float)):
        return abs(wanted - reported) < 1e-9
    return type(wanted) is type(reported) and wanted == reported


def _applied_already_logged(db: Session, row: DeviceCommand) -> bool:
    return (
        db.scalars(
            select(CommandLogEntry.id)
            .where(
                CommandLogEntry.command_id == row.id,
                CommandLogEntry.direction == CommandLogDirection.FROM_DEVICE,
                CommandLogEntry.status == "success",
                CommandLogEntry.occurred_at >= row.delivered_at,
            )
            .limit(1)
        ).first()
        is not None
    )


def _log_queue_event(
    db: Session, row: DeviceCommand, status: str, occurred_at: datetime | None = None
) -> None:
    is_config = row.type == CommandType.CONFIG_OVERRIDE
    entry = CommandLogEntry(
        device_id=row.device_id,
        direction=CommandLogDirection.TO_DEVICE,
        kind="config" if is_config else "command",
        name=row.field if is_config else row.payload["command"],
        command_id=row.id,
        status=status,
    )
    if occurred_at is not None:
        entry.occurred_at = occurred_at
    db.add(entry)


@router.post(
    "",
    response_model=HeartbeatResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
    summary="Receive a heartbeat (device)",
    description=(
        "Device endpoint: stores a heartbeat and answers with the config overrides and "
        "one-shot commands queued for the device. The device authenticates with its "
        "`X-Device-ID` and `X-Device-Key` headers.\n\n"
        "**Delivery.** A response with active overrides or pending commands carries "
        "`config_overrides` (field to value; a `null` value tells the device to reset that "
        "override) and `commands` (`[{\"id\": 42, \"command\": \"force-upload-now\"}]`). Both "
        "are omitted entirely when nothing is queued. Overrides stay in every response until "
        "replaced or removed. Commands are delivered at least once, so the device dedupes on "
        "`id`, until it acknowledges them, they are removed from the queue, or they expire 24 "
        "hours after being queued. Every response carries a `signature`, `hmac-sha256:<hex "
        "digest>`: an HMAC-SHA256 over the exact JSON body excluding the `signature` field, "
        "keyed by the device's own HMAC secret. If the request carried a `nonce` (1 to 64 "
        "characters of `[A-Za-z0-9]`, otherwise 422), it is echoed inside the signed body of "
        "every response, so the device can tell a fresh response from a replayed one.\n\n"
        "**Acknowledgements.** The payload may carry `executed_commands`, the device's report "
        "of what it did with delivered one-shot commands: `[{\"id\": 45, \"command\": "
        "\"promote-overrides-now\", \"status\": \"success\", \"error\": null}]`. The fields are "
        "plain strings and numbers, and a `command` or `status` the backend does not know is "
        "never a reason to reject the heartbeat. `status` is `success`, `failed`, "
        "`not_applicable` (the command's precondition was not met, such as `sim-reset-now` "
        "without an active measurement) or `received`. `error` is `null` on success, otherwise "
        "the reason. The first terminal acknowledgement removes the command from the queue, "
        "which stops its redelivery; the device keeps resending the result for as long as the "
        "command is redelivered. `received` is terminal only for `shutdown-now`, whose result "
        "is otherwise inferred from the heartbeats that follow; a `success` the device sends "
        "for it after the next boot is still recorded, and wins over an inferred result that "
        "came later. `reboot-now` acknowledges twice: "
        "`received` first, which keeps the command queued, then `success` once the device is "
        "back up. An unrecognized `status` is logged and the command stays queued. Config "
        "overrides are never acknowledged this way: an override counts as applied once "
        "`current_config` shows its value.\n\n"
        "`current_config` (at most 4096 bytes, otherwise 413) is the device's live in-effect "
        "config, readable through the dashboard heartbeat endpoints by superusers only. "
        "`run_phase`, `gps_fix` and `critical_error` are optional. 401 for missing or wrong "
        "device credentials, 422 for an invalid payload."
    ),
)
async def receive_heartbeat(
    payload: HeartbeatPayload,
    background_tasks: BackgroundTasks,
    device: Device = Depends(verify_device_auth),
    db: Session = Depends(get_db),
    channel: NotificationChannel = Depends(get_notification_channel),
) -> HeartbeatResponse:
    """Receive and store a heartbeat from a device, returning any queued overrides/commands."""
    if payload.current_config is not None:
        size = len(json.dumps(payload.current_config).encode("utf-8"))
        if size > _MAX_CURRENT_CONFIG_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"current_config exceeds the {_MAX_CURRENT_CONFIG_BYTES}-byte limit",
            )

    device_id = device.device_id
    received_at = datetime.now(UTC)

    # Recorded before any shutdown result is inferred below, so the device's own word wins.
    acked_events: list[tuple[str, int, str, str | None]] = []
    late_shutdown_successes = record_reported_shutdown_successes(
        db,
        device_id,
        [ack.id for ack in payload.executed_commands or [] if ack.status == "success"],
    )
    if late_shutdown_successes:
        db.flush()
    for command_id in late_shutdown_successes:
        acked_events.append(("shutdown-now", command_id, "success", None))

    # A heartbeat after a long silence is how a shutdown-now that nobody looked at in the
    # meantime gets confirmed: the device was off for the gap.
    previous_heartbeat = db.scalars(
        select(Heartbeat)
        .where(Heartbeat.device_id == device_id)
        .order_by(Heartbeat.received_at.desc())
        .limit(1)
    ).first()
    previous_state = None
    if previous_heartbeat is not None:
        heartbeat_interval_s = device_heartbeat_interval_s(db, device_id)
        confirm_shutdowns(
            db,
            device_id,
            previous_heartbeat.received_at,
            heartbeat_interval_s,
            received_at,
            get_shutdown_confirmation(db),
        )
        previous_state = {
            "previous_run_phase": previous_heartbeat.run_phase,
            "previous_pipeline_broken": previous_heartbeat.pipeline_broken,
            "previous_received_at": previous_heartbeat.received_at,
            "heartbeat_interval_s": heartbeat_interval_s,
        }

    heartbeat = Heartbeat(
        device_id=device_id,
        received_at=received_at,
        datapoints_total=payload.datapoints_total,
        datapoints_valid=payload.datapoints_valid,
        datapoints_invalid=payload.datapoints_invalid,
        pipeline_broken=payload.pipeline_broken,
        storage_pending_files=payload.storage_pending_files,
        storage_disk_free_bytes=payload.storage_disk_free_bytes,
        current_config=payload.current_config,
        run_phase=payload.run_phase.value if payload.run_phase is not None else None,
        gps_fix=payload.gps_fix.model_dump() if payload.gps_fix is not None else None,
        critical_error=(
            payload.critical_error.model_dump() if payload.critical_error is not None else None
        ),
    )
    db.add(heartbeat)
    db.flush()  # so the failure check below counts this heartbeat (the session doesn't autoflush)
    fail_unresponsive_shutdowns(db, device_id)

    # Clear the queue row for every acked command this device still owns, before querying what
    # to redeliver below - an acked command has nothing left to redeliver.
    failed_command_ack = False
    if payload.executed_commands:
        acked_rows = {
            row.id: row
            for row in db.scalars(
                select(DeviceCommand).where(
                    DeviceCommand.device_id == device_id,
                    DeviceCommand.type == CommandType.ONE_SHOT,
                    DeviceCommand.id.in_([ack.id for ack in payload.executed_commands]),
                )
            ).all()
        }
        for ack in payload.executed_commands:
            row = acked_rows.get(ack.id)
            if row is None:
                continue  # already cleared by an earlier ack, or not a command we queued
            if ack.status not in _KNOWN_STATUSES:
                logger.warning(
                    "Unrecognized command-ack status %r: device_id=%s command_id=%s command=%s "
                    "- leaving it queued",
                    ack.status, device_id, ack.id, row.payload["command"],
                )
                continue
            command = row.payload["command"]
            terminal = ack.status in _TERMINAL_STATUSES or (
                ack.status == "received" and command in RECEIVED_IS_TERMINAL_FOR
            )
            # Notify (log + toast) for every known-status ack, terminal or not - reboot-now's
            # non-terminal "received" still needs to show up, it just doesn't clear the row.
            acked_events.append((command, ack.id, ack.status, ack.error))
            failed_command_ack = failed_command_ack or ack.status == "failed"
            db.add(
                CommandLogEntry(
                    device_id=device_id,
                    direction=CommandLogDirection.FROM_DEVICE,
                    kind="command",
                    name=command,
                    command_id=ack.id,
                    status=ack.status,
                    detail=ack.error,
                )
            )
            if terminal:
                db.delete(row)
        # The session is autoflush=False (app/db.py), so without this, the just-deleted row(s)
        # would still be visible to the command_rows query below and get redelivered in this
        # same response - the one response that is acking them as done.
        db.flush()

    now = datetime.now(UTC)

    override_rows = db.scalars(
        select(DeviceCommand).where(
            DeviceCommand.device_id == device.device_id,
            DeviceCommand.type == CommandType.CONFIG_OVERRIDE,
        )
    ).all()
    config_overrides = {
        row.field: row.payload["value"]
        for row in override_rows
        if row.field in _ALLOWED_OVERRIDE_FIELDS
    }
    # Overrides are re-sent on every heartbeat, so only the first delivery after (re-)queueing
    # is stamped and logged; queue_config_overrides resets delivered_at when it replaces a value.
    for row in override_rows:
        if row.field not in _ALLOWED_OVERRIDE_FIELDS:
            continue
        if row.delivered_at is None:
            row.delivered_at = now
            _log_queue_event(db, row, "delivered")
        elif _override_is_applied(row, payload.current_config) and not _applied_already_logged(
            db, row
        ):
            # This heartbeat was sent before the device saw the response that first carried the
            # override, so a delivery in an earlier heartbeat plus a matching value here means the
            # device took it up. Overrides get no ack, so this is their only confirmation.
            db.add(
                CommandLogEntry(
                    device_id=row.device_id,
                    direction=CommandLogDirection.FROM_DEVICE,
                    kind="config",
                    name=row.field,
                    command_id=row.id,
                    status="success",
                    detail=f"current value = {row.payload['value']}",
                )
            )

    # An expired one-shot is never delivered again; drop its row here, where the queue is being
    # read anyway, and log when it expired so its timeline can end on that.
    expired_rows = db.scalars(
        select(DeviceCommand).where(
            DeviceCommand.device_id == device.device_id,
            DeviceCommand.type == CommandType.ONE_SHOT,
            DeviceCommand.expires_at.is_not(None),
            DeviceCommand.expires_at <= now,
        )
    ).all()
    for row in expired_rows:
        _log_queue_event(db, row, "expired", occurred_at=row.expires_at)
        db.delete(row)

    command_rows = db.scalars(
        select(DeviceCommand)
        .where(
            DeviceCommand.device_id == device.device_id,
            DeviceCommand.type == CommandType.ONE_SHOT,
            (DeviceCommand.expires_at.is_(None)) | (DeviceCommand.expires_at > now),
        )
        # Without an explicit order, row order is unspecified - the device is expected to
        # apply commands in the order given, so an unstable order risks e.g. a stale
        # re-delivered stop-gps-fix-test-now landing after a newer run-gps-fix-test-now. `id`
        # breaks ties between commands created within the same timestamp (e.g. a mode switch
        # followed by a reboot), keeping creation order.
        .order_by(DeviceCommand.created_at, DeviceCommand.id)
    ).all()
    commands = []
    promotion_newly_delivered = False
    for row in command_rows:
        if (
            row.payload["command"] == OneShotCommand.PROMOTE_OVERRIDES_NOW
            and row.delivered_at is None
        ):
            promotion_newly_delivered = True
        if row.delivered_at is None:
            _log_queue_event(db, row, "delivered")
        row.delivered_at = now
        commands.append({"id": row.id, "command": row.payload["command"]})

    # The overrides were read above, so this response still carries them; the device writes them
    # to its overrides file before running the promotion. Only the first delivery clears, so
    # overrides queued after it survive the command's at-least-once redelivery.
    if promotion_newly_delivered:
        for row in override_rows:
            _log_queue_event(db, row, "promoted")
        db.execute(
            delete(DeviceCommand).where(
                DeviceCommand.device_id == device.device_id,
                DeviceCommand.type == CommandType.CONFIG_OVERRIDE,
            )
        )

    db.commit()
    if previous_state is not None:
        events = detect_heartbeat_events(
            **previous_state,
            received_at=received_at,
            run_phase=payload.run_phase,
            pipeline_broken=payload.pipeline_broken,
            failed_command_ack=failed_command_ack,
        )
        prepared = prepare_notifications(db, events, device_id, received_at)
        if prepared:
            background_tasks.add_task(deliver, channel, prepared)
    heartbeat_broadcaster.publish(device_id, received_at)
    for command, command_id, ack_status, error in acked_events:
        logger.info(
            "Command ack: device_id=%s command_id=%s command=%s status=%s error=%s",
            device_id, command_id, command, ack_status, error,
        )
        command_ack_broadcaster.publish(
            device_id, command_id, command, ack_status, error, received_at
        )

    body = {"status": "ok", "message": "Heartbeat received"}
    if config_overrides:
        body["config_overrides"] = config_overrides
    if commands:
        body["commands"] = commands
    if payload.nonce is not None:
        body["nonce"] = payload.nonce
    signature = sign_heartbeat_response(device, body)

    return HeartbeatResponse(**body, signature=signature)


@router.get(
    "",
    response_model=HeartbeatListResponse,
    summary="Get the latest heartbeat of every device",
    description=(
        "Requires a logged-in user (any account). The latest heartbeat of each registered "
        "device, for the dashboard, as `DeviceHeartbeatSummary` entries. `current_config`, the "
        "device's live in-effect config as last reported, and `critical_error` are populated "
        "for superusers only and `null` for other callers, as they are when the device has not "
        "reported them. The device's mode stays visible to every caller as `system_mode`. "
        "`current_config` is read-only: it comes purely from what the device reports. "
        "401 without a valid token."
    ),
)
async def get_latest_heartbeats(
    db: Session = Depends(get_db),
    user: User = Depends(current_active_user),
) -> HeartbeatListResponse:
    """Get the latest heartbeat for each device."""
    # Query to get the latest heartbeat per device
    # Using a subquery to find the max received_at for each device
    subquery = (
        select(
            Heartbeat.device_id,
            func.max(Heartbeat.received_at).label("latest_received_at"),
        )
        .group_by(Heartbeat.device_id)
        .subquery()
    )

    # Join with the main table to get full heartbeat data
    query = (
        select(Heartbeat)
        .join(
            subquery,
            (Heartbeat.device_id == subquery.c.device_id)
            & (Heartbeat.received_at == subquery.c.latest_received_at),
        )
        .order_by(Heartbeat.device_id)
    )

    heartbeats = db.scalars(query).all()

    summaries = [
        DeviceHeartbeatSummary(
            device_id=h.device_id,
            received_at=h.received_at.isoformat() if h.received_at else "",
            datapoints_total=h.datapoints_total,
            datapoints_valid=h.datapoints_valid,
            datapoints_invalid=h.datapoints_invalid,
            pipeline_broken=h.pipeline_broken,
            storage_pending_files=h.storage_pending_files,
            storage_disk_free_bytes=h.storage_disk_free_bytes,
            current_config=h.current_config if user.is_superuser else None,
            run_phase=h.run_phase,
            gps_fix=h.gps_fix,
            critical_error=h.critical_error if user.is_superuser else None,
            system_mode=reported_system_mode(h.current_config),
        )
        for h in heartbeats
    ]

    return HeartbeatListResponse(heartbeats=summaries)


async def event_stream(
    subscription: Subscription, keepalive_s: float = _KEEPALIVE_INTERVAL_S
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
    "/stream",
    response_class=StreamingResponse,
    summary="Stream a signal for each new heartbeat of a device",
    description=(
        "Server-Sent Events (`text/event-stream`), held open. Signals that the heartbeat of "
        "`device_id` just arrived, so the dashboard can reload at once instead of waiting for "
        "its next poll:\n\n"
        "```\n: connected\n\nevent: heartbeat\n"
        "data: {\"device_id\": \"5gmu_1\", \"received_at\": \"2026-01-01T00:00:30+00:00\"}\n\n"
        ": keep-alive\n```\n\n"
        "Requires a token of any active user, the same access level as `GET /heartbeat`; "
        "device credentials are not accepted. The native `EventSource` cannot send the "
        "`Authorization` header, so clients use `fetch()` and read the response body as a "
        "stream; never put the token in the URL. Lines starting with `:` are comments: "
        "`: connected` is sent on open and `: keep-alive` after every 20 seconds of silence "
        "so proxies keep the idle connection open (devices heartbeat about once a minute).\n\n"
        "An event is a signal only: it never carries the heartbeat payload or "
        "`current_config`; clients fetch the data through `GET /heartbeat`, which applies its "
        "own serialization and superuser-only field filtering. Events are coalesced: if a "
        "subscriber has not consumed the previous event, the newer one replaces it. Missed "
        "events are not replayed after a reconnect. Subscribers live in memory of one server "
        "process.\n\n"
        "Errors: 401 for a missing or invalid token, 404 if `device_id` is not a registered "
        "device, 422 for a missing or empty `device_id`, 429 when the per-user (5) or global "
        "(100) limit of concurrent streams is reached."
    ),
)
async def stream_heartbeat_events(
    device_id: str = Query(min_length=1),
    db: Session = Depends(get_db),
    user: User = Depends(current_active_user),
) -> StreamingResponse:
    if db.get(Device, device_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    try:
        subscription = heartbeat_broadcaster.subscribe(device_id, user.id)
    except StreamLimitExceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many open streams"
        ) from None

    return StreamingResponse(
        event_stream(subscription),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        # The generator's `finally` only runs once it has started; this covers a client that
        # disconnects before the body starts so the subscriber slot cannot leak.
        background=BackgroundTask(subscription.close),
    )


@router.get(
    "/{device_id}",
    response_model=DeviceHeartbeatSummary,
    summary="Get the latest heartbeat of one device",
    description=(
        "Requires a logged-in user (any account). The latest heartbeat of one device, with "
        "the same superuser-only filtering of `current_config` and `critical_error` as "
        "`GET /heartbeat`. 401 without a valid token, 404 if the device is unknown or has "
        "not sent a heartbeat."
    ),
)
async def get_device_heartbeat(
    device_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_active_user),
) -> DeviceHeartbeatSummary:
    """Get the latest heartbeat for a specific device."""
    # Get the latest heartbeat for this device
    query = (
        select(Heartbeat)
        .where(Heartbeat.device_id == device_id)
        .order_by(Heartbeat.received_at.desc())
        .limit(1)
    )

    heartbeat = db.scalars(query).first()

    if not heartbeat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No heartbeats found for device '{device_id}'",
        )

    return DeviceHeartbeatSummary(
        device_id=heartbeat.device_id,
        received_at=heartbeat.received_at.isoformat() if heartbeat.received_at else "",
        datapoints_total=heartbeat.datapoints_total,
        datapoints_valid=heartbeat.datapoints_valid,
        datapoints_invalid=heartbeat.datapoints_invalid,
        pipeline_broken=heartbeat.pipeline_broken,
        storage_pending_files=heartbeat.storage_pending_files,
        storage_disk_free_bytes=heartbeat.storage_disk_free_bytes,
        current_config=heartbeat.current_config if user.is_superuser else None,
        run_phase=heartbeat.run_phase,
        gps_fix=heartbeat.gps_fix,
        critical_error=heartbeat.critical_error if user.is_superuser else None,
        system_mode=reported_system_mode(heartbeat.current_config),
    )
