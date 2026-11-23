"""Maintainer-facing API for queuing device config overrides and one-shot commands.

Superuser-JWT-gated only, mirroring the superuser auth boundary - a device's own
X-Device-ID/X-Device-Key credentials never grant access here. Queued items are delivered to
the device on its next heartbeat response (see app/routers/heartbeat.py).
"""
import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.app_settings import get_shutdown_confirmation
from app.auth import current_superuser
from app.command_events import StreamLimitExceeded, Subscription, command_ack_broadcaster
from app.command_status import (
    SHUTDOWN_FAIL_HEARTBEATS,
    build_command_status,
    confirm_shutdowns,
    device_heartbeat_interval_s,
    required_silence,
)
from app.db import get_db
from app.models import (
    CommandLogDirection,
    CommandLogEntry,
    CommandStatusDismissal,
    CommandType,
    Device,
    DeviceCommand,
    Heartbeat,
)
from app.models.user import User
from app.schemas import ApiResponse
from app.schemas.commands import (
    CommandCreate,
    CommandDismissRequest,
    CommandDismissResponse,
    CommandLogItem,
    CommandLogResponse,
    CommandQueuedResponse,
    CommandStatusEntry,
    CommandStatusResponse,
    ConfigOverrideCreate,
    ConfigOverrideQueuedResponse,
    QueueEntry,
    QueueListResponse,
)

router = APIRouter(prefix="/devices/{device_id}", tags=["commands"])
# Global (not per-device), like app/routers/measurements.py's /measurements/stream - a client
# queuing a command doesn't know in advance which device's ack will land first.
stream_router = APIRouter(tags=["commands"])

COMMAND_STATUS_DEFAULT_LIMIT = 20
COMMAND_LOG_DEFAULT_LIMIT = 100
COMMAND_LOG_MAX_LIMIT = 500

ONE_SHOT_COMMAND_TTL = timedelta(hours=24)

# Acks can arrive minutes to hours apart (next heartbeat, or never for a dropped/offline
# device), unlike heartbeats' roughly-once-a-minute cadence - a keep-alive still matters so a
# proxy doesn't close the idle connection.
_COMMAND_ACK_KEEPALIVE_INTERVAL_S = 20


def _get_device_or_404(device_id: str, db: Session) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown device '{device_id}'",
        )
    return device


def _removal_log_entry(row: DeviceCommand) -> CommandLogEntry:
    is_config = row.type == CommandType.CONFIG_OVERRIDE
    return CommandLogEntry(
        device_id=row.device_id,
        direction=CommandLogDirection.TO_DEVICE,
        kind="config" if is_config else "command",
        name=row.field if is_config else row.payload["command"],
        command_id=row.id,
        status="removed",
    )


@router.post(
    "/config-overrides",
    response_model=ConfigOverrideQueuedResponse,
    summary="Queue config overrides for a device",
    description=(
        "Superuser only; the device's own credentials are rejected with 401. Queues one or "
        "more config field overrides, delivered on the device's next heartbeat response. The "
        "body is any subset of the allow-listed fields (see the `ConfigOverrideCreate` "
        "schema); a field that is not sent is not overridden, and anything outside the "
        "allow-list is rejected. Each field replaces any existing override for that field "
        "(no duplicate rows) and stays in effect, included in every subsequent heartbeat "
        "response, until replaced or removed with `DELETE /devices/{device_id}/queue/{id}`. "
        "`null` is accepted only for the nullable fields, where it resets the override so the "
        "device falls back to its own configuration. Booleans and integers are strict: `1` "
        "is not a boolean, `3.5` is not an integer, strings are never coerced, and "
        "`NaN` and infinity are rejected. Not accepted: `system_mode`, which the device "
        "reports in `current_config` and which only changes through the `mode-manual-now` "
        "and `mode-auto-now` commands; device identity, secrets and network settings are "
        "permanently excluded from remote override.\n\n"
        "The `modem_*`, `gnss_receiver_*` and `system_running_on_pi` fields can degrade or "
        "disable a device in the field; the dashboard asks for confirmation, and the bounds "
        "are the backend's only guard.\n\n"
        "Answers `{\"status\": \"ok\", \"config_overrides\": {...}}` with the queued fields. "
        "Errors: 400 if no override field was provided, 401 without a valid token or with "
        "device-key authentication, 403 for a non-superuser, 404 if `device_id` is not a "
        "registered device, 422 for a field outside the allow-list or a value of the wrong "
        "type, out of range, or `null` for a field that is not nullable. The 422 names the "
        "field and the violated constraint, never the submitted value."
    ),
)
async def queue_config_overrides(
    device_id: str,
    payload: ConfigOverrideCreate,
    db: Session = Depends(get_db),
    _: User = Depends(current_superuser),
) -> ConfigOverrideQueuedResponse:
    _get_device_or_404(device_id, db)

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No config override fields provided",
        )

    for field, value in fields.items():
        row = db.scalars(
            select(DeviceCommand).where(
                DeviceCommand.device_id == device_id,
                DeviceCommand.type == CommandType.CONFIG_OVERRIDE,
                DeviceCommand.field == field,
            )
        ).first()
        if row is not None:
            row.payload = {"value": value}
            row.delivered_at = None
        else:
            row = DeviceCommand(
                device_id=device_id,
                type=CommandType.CONFIG_OVERRIDE,
                field=field,
                payload={"value": value},
            )
            db.add(row)
            db.flush()  # assigns row.id, which the log row records
        db.add(
            CommandLogEntry(
                device_id=device_id,
                direction=CommandLogDirection.TO_DEVICE,
                kind="config",
                name=field,
                command_id=row.id,
                status="queued",
                detail=f"= {value}",
            )
        )

    db.commit()

    return ConfigOverrideQueuedResponse(status="ok", config_overrides=fields)


@router.post(
    "/commands",
    response_model=CommandQueuedResponse,
    summary="Queue a one-shot command for a device",
    description=(
        "Superuser only; the device's own credentials are rejected with 401. Queues a one-shot "
        "command, delivered on heartbeat responses at least once (the device dedupes on the "
        "returned `command_id`) until the device acknowledges it, it is removed with "
        "`DELETE /devices/{device_id}/queue/{id}`, or it expires 24 hours after being queued. "
        "Body `{\"command\": \"force-upload-now\"}`; answers `{\"status\": \"ok\", "
        "\"command_id\": 42}`. No command takes parameters.\n\n"
        "Commands: `force-upload-now`; `shutdown-now`; `sim-reset-now`; `reboot-now`; "
        "`mode-manual-now` and `mode-auto-now`, which switch the device to Manual or Auto "
        "Mode on its next boot; `start-measuring-now`, which in Manual "
        "Mode, or when idle after a crash recovery, leaves the idle loop and starts measuring "
        "in the same boot; `stop-measuring-now`, which stops the current measurement run: the "
        "device finalizes, uploads, shuts down and boots into Manual Mode once; "
        "`run-selftest-now`, which in Manual Mode runs the device self-test; "
        "`run-gps-fix-test-now` and `stop-gps-fix-test-now`, which start and stop the live "
        "GPS-fix diagnostic (see `GET /devices/{device_id}/gps-fix-test/status`); and "
        "`promote-overrides-now`, which bakes the device's override file into its standard "
        "configuration. When "
        "`promote-overrides-now` is first delivered, the backend deletes all of the device's "
        "queued config overrides; that heartbeat response still carries the current "
        "overrides, so the device writes them before running the promotion.\n\n"
        "Acknowledgements and results are reported by the device through `POST /heartbeat`. "
        "Errors: as for queuing config overrides, with 422 for a command outside the list."
    ),
)
async def queue_command(
    device_id: str,
    payload: CommandCreate,
    db: Session = Depends(get_db),
    _: User = Depends(current_superuser),
) -> CommandQueuedResponse:
    _get_device_or_404(device_id, db)

    command_payload = {"command": payload.command.value}

    now = datetime.now(UTC)
    command = DeviceCommand(
        device_id=device_id,
        type=CommandType.ONE_SHOT,
        payload=command_payload,
        expires_at=now + ONE_SHOT_COMMAND_TTL,
    )
    db.add(command)
    db.flush()  # assigns command.id, which the log row records
    db.add(
        CommandLogEntry(
            device_id=device_id,
            direction=CommandLogDirection.TO_DEVICE,
            kind="command",
            name=payload.command.value,
            command_id=command.id,
            status="queued",
        )
    )
    db.commit()

    return CommandQueuedResponse(status="ok", command_id=command.id)


@router.get(
    "/queue",
    response_model=QueueListResponse,
    summary="List queued config overrides and commands for a device",
    description=(
        "Superuser only. Every queued config override and one-shot command of the device, "
        "including those already delivered but not yet removed, oldest first. Each entry has "
        "`id`, `type` (`config_override` or `one_shot`), `field` (the config field, `null` "
        "for a command), `payload` (`{\"value\": ...}` or `{\"command\": ...}`), `created_at`, "
        "`delivered_at` and `expires_at` (`null` for overrides, which do not expire). 401 "
        "without a valid token, 403 for a non-superuser, 404 for an unknown device."
    ),
)
async def list_queue(
    device_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(current_superuser),
) -> QueueListResponse:
    _get_device_or_404(device_id, db)

    rows = db.scalars(
        select(DeviceCommand)
        .where(DeviceCommand.device_id == device_id)
        .order_by(DeviceCommand.created_at)
    ).all()

    return QueueListResponse(
        queue=[
            QueueEntry(
                id=row.id,
                type=row.type.value,
                field=row.field,
                payload=row.payload,
                created_at=row.created_at.isoformat() if row.created_at else "",
                delivered_at=row.delivered_at.isoformat() if row.delivered_at else None,
                expires_at=row.expires_at.isoformat() if row.expires_at else None,
            )
            for row in rows
        ]
    )


@router.get(
    "/command-status",
    response_model=CommandStatusResponse,
    summary="Lifecycle of the device's most recent commands and config overrides",
    description=(
        "Superuser only. The lifecycle of the device's most recently active commands and "
        "config overrides, newest first, including commands whose queue row an "
        "acknowledgement has already cleared and without those a maintainer dismissed. "
        "`limit` is 1 to 500 (default 20).\n\n"
        "Each item has `command_id`, `kind` (`config` or `command`), `name`, `detail` "
        "(`= <value>` for a config override), `state`, `complete`, `in_queue`, the timestamps "
        "`queued_at`, `delivered_at`, `received_at`, `result_at`, `removed_at`, `promoted_at`, "
        "`expired_at` and `expires_at`, and `error`, the reason of a `failed` or "
        "`not_applicable` result (`null` otherwise). `state` is `queued`, `delivered`, "
        "`received`, `success`, `failed`, `not_applicable`, `promoted`, `removed` or "
        "`expired`. A config override's `success` means the device's reported "
        "`current_config` shows the new value; `promoted` is an override that "
        "`promote-overrides-now` made the device's baseline, and it is never reported back. "
        "Expired one-shot commands are removed from the queue on the device's next "
        "heartbeat.\n\n"
        "The response also has `last_heartbeat_at`, `heartbeat_interval_s` and the effective "
        "shutdown confirmation rule (see `GET /settings/shutdown-confirmation`): "
        "`shutdown_confirm_mode` (`intervals`, the default of 4 heartbeat intervals, or "
        "`seconds`), `shutdown_confirm_seconds`, the effective span in seconds in both modes, "
        "and `shutdown_confirm_intervals`, the same span in heartbeat intervals (fractional in "
        "`seconds` mode). A `shutdown-now` stays `received` until the device has sent no "
        "heartbeat for that span, then becomes `success`; reading this endpoint records that. "
        "If the device instead sends `shutdown_fail_heartbeats` (10) more heartbeats after "
        "the acknowledgement, it becomes `failed`."
    ),
)
async def list_command_status(
    device_id: str,
    limit: int = Query(COMMAND_STATUS_DEFAULT_LIMIT, ge=1, le=COMMAND_LOG_MAX_LIMIT),
    db: Session = Depends(get_db),
    _: User = Depends(current_superuser),
) -> CommandStatusResponse:
    _get_device_or_404(device_id, db)

    latest_heartbeat = db.scalars(
        select(Heartbeat)
        .where(Heartbeat.device_id == device_id)
        .order_by(Heartbeat.received_at.desc())
        .limit(1)
    ).first()
    interval_s = device_heartbeat_interval_s(db, device_id)
    confirmation = get_shutdown_confirmation(db)
    if latest_heartbeat is not None:
        confirm_shutdowns(
            db,
            device_id,
            latest_heartbeat.received_at,
            interval_s,
            datetime.now(UTC),
            confirmation,
        )
        db.commit()

    queue_rows = db.scalars(
        select(DeviceCommand).where(DeviceCommand.device_id == device_id)
    ).all()
    dismissed_at = dict(
        db.execute(
            select(CommandStatusDismissal.command_id, CommandStatusDismissal.dismissed_at).where(
                CommandStatusDismissal.device_id == device_id
            )
        ).all()
    )
    last_activity = func.max(CommandLogEntry.occurred_at)
    # Commands dismissed and not active since are skipped here, not only in build_command_status,
    # so they do not use up the limit's slots.
    recent_ids = (
        select(CommandLogEntry.command_id)
        .outerjoin(
            CommandStatusDismissal,
            (CommandStatusDismissal.device_id == CommandLogEntry.device_id)
            & (CommandStatusDismissal.command_id == CommandLogEntry.command_id),
        )
        .where(CommandLogEntry.device_id == device_id, CommandLogEntry.command_id.is_not(None))
        .group_by(CommandLogEntry.command_id, CommandStatusDismissal.dismissed_at)
        .having(
            or_(
                CommandStatusDismissal.dismissed_at.is_(None),
                last_activity > CommandStatusDismissal.dismissed_at,
            )
        )
        .order_by(last_activity.desc())
        .limit(limit)
    )
    log_rows = db.scalars(
        select(CommandLogEntry).where(
            CommandLogEntry.device_id == device_id,
            CommandLogEntry.command_id.in_(recent_ids),
        )
    ).all()

    def iso(value):
        return value.isoformat() if value else None

    confirm_span_s = required_silence(confirmation, interval_s).total_seconds()
    return CommandStatusResponse(
        items=[
            CommandStatusEntry(
                command_id=item.command_id,
                kind=item.kind,
                name=item.name,
                detail=item.detail,
                state=item.state,
                complete=item.complete,
                in_queue=item.in_queue,
                queued_at=iso(item.queued_at),
                delivered_at=iso(item.delivered_at),
                received_at=iso(item.received_at),
                result_at=iso(item.result_at),
                removed_at=iso(item.removed_at),
                promoted_at=iso(item.promoted_at),
                expired_at=iso(item.expired_at),
                expires_at=iso(item.expires_at),
                error=item.error,
            )
            for item in build_command_status(queue_rows, log_rows, limit, dismissed_at)
        ],
        last_heartbeat_at=iso(latest_heartbeat.received_at) if latest_heartbeat else None,
        heartbeat_interval_s=interval_s,
        shutdown_confirm_mode=confirmation.mode,
        shutdown_confirm_intervals=confirm_span_s / interval_s,
        shutdown_confirm_seconds=confirm_span_s,
        shutdown_fail_heartbeats=SHUTDOWN_FAIL_HEARTBEATS,
    )


@router.post(
    "/command-status/dismiss",
    response_model=CommandDismissResponse,
    summary="Delete finished commands from the command status",
    description=(
        "Superuser only (401 without a token, 403 for a non-superuser, 404 for an unknown "
        "device). \"Delete shown\": hides finished commands from `GET .../command-status`, "
        "which the Remote Configuration page, the Find GPS Fix dialog and the Mission Status "
        "section show. Body `{\"command_ids\": [41, 42]}` with 1 to 500 positive integers; "
        "extra fields are rejected with 422. Only ids of this device that are finished "
        "(`complete` and not `in_queue`) are dismissed, so an applied config override, which "
        "stays in the queue, is never dismissed. Every other id (in progress, unknown, another "
        "device's) is ignored, so a stale client list cannot hide a command that is still in "
        "progress. Answers `{\"dismissed\": [41]}` with the ids that were hidden, ascending. "
        "The call is idempotent. A dismissed command shows up again if it has activity after "
        "the dismissal, for example when it is re-queued. The `limit` of the status endpoint "
        "counts only commands that are not dismissed, and `GET /command-log` is not affected."
    ),
)
async def dismiss_command_status(
    device_id: str,
    payload: CommandDismissRequest,
    db: Session = Depends(get_db),
    _: User = Depends(current_superuser),
) -> CommandDismissResponse:
    _get_device_or_404(device_id, db)

    requested_ids = set(payload.command_ids)
    queue_rows = db.scalars(
        select(DeviceCommand).where(
            DeviceCommand.device_id == device_id, DeviceCommand.id.in_(requested_ids)
        )
    ).all()
    log_rows = db.scalars(
        select(CommandLogEntry).where(
            CommandLogEntry.device_id == device_id, CommandLogEntry.command_id.in_(requested_ids)
        )
    ).all()
    finished_ids = sorted(
        item.command_id
        for item in build_command_status(queue_rows, log_rows, limit=len(requested_ids))
        if item.finished
    )

    if finished_ids:
        statement = insert(CommandStatusDismissal).values(
            [{"device_id": device_id, "command_id": command_id} for command_id in finished_ids]
        )
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    CommandStatusDismissal.device_id,
                    CommandStatusDismissal.command_id,
                ],
                set_={"dismissed_at": func.now()},
            )
        )
        db.commit()

    return CommandDismissResponse(dismissed=finished_ids)


@router.delete(
    "/queue/{command_id}",
    response_model=ApiResponse,
    summary="Delete a queued config override or command",
    description=(
        "Superuser only. Removes a queued config override or one-shot command so it stops "
        "being delivered on future heartbeats. Use it for a command the device will never "
        "acknowledge, for example because it is offline or predates acknowledgements. "
        "Answers `{\"status\": \"ok\", \"message\": \"Deleted queued item 42\"}`. 401 without a "
        "valid token, 403 for a non-superuser, 404 if the device is not registered or has no "
        "queued item with that id."
    ),
)
async def delete_queue_entry(
    device_id: str,
    command_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(current_superuser),
) -> ApiResponse:
    _get_device_or_404(device_id, db)

    row = db.get(DeviceCommand, command_id)
    if row is None or row.device_id != device_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No queued item with id {command_id} for device '{device_id}'",
        )

    db.add(_removal_log_entry(row))
    db.delete(row)
    db.commit()

    return ApiResponse(status="ok", message=f"Deleted queued item {command_id}")


@router.delete(
    "/queue",
    response_model=ApiResponse,
    summary="Clear the entire queue for a device",
    description=(
        "Superuser only. Clears the entire queue of the device in one action: every queued "
        "config override and one-shot command, whatever its type or field. It is not scoped "
        "to any filter and cannot be undone, like the single-item delete. An empty queue is "
        "not an error: deleting 0 items still answers 200, with a message such as \"Deleted 3 "
        "queued item(s) for device 'raspberrypi-01'\". 401 without a valid token, 403 for a "
        "non-superuser, 404 if the device is not registered."
    ),
)
async def clear_queue(
    device_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(current_superuser),
) -> ApiResponse:
    _get_device_or_404(device_id, db)

    rows = db.scalars(select(DeviceCommand).where(DeviceCommand.device_id == device_id)).all()
    db.add_all(_removal_log_entry(row) for row in rows)
    result = db.execute(sql_delete(DeviceCommand).where(DeviceCommand.device_id == device_id))
    db.commit()

    return ApiResponse(
        status="ok",
        message=f"Deleted {result.rowcount} queued item(s) for device '{device_id}'",
    )


@stream_router.get(
    "/command-log",
    response_model=CommandLogResponse,
    summary="List the persisted command/override communication history",
    description=(
        "Superuser only. The persisted, newest-first history of everything queued for devices "
        "and every acknowledgement devices sent back. Unlike the queue, entries are not "
        "removed by acknowledgements or the 24 hour expiry. Query parameters: `device_id` "
        "(optional filter) and `limit` (1 to 500, default 100).\n\n"
        "Each entry has `id`, `occurred_at`, `device_id`, `direction`, `kind`, `name`, "
        "`command_id`, `status` and `detail`. `direction` is `to_device` (`status` is "
        "`queued`, `delivered`, `removed`, `promoted` or `expired`) or `from_device` (an "
        "acknowledgement: `status` is `success`, `failed`, `not_applicable` or `received` and "
        "`detail` the device's error text; for a config override, `success` means "
        "`current_config` shows the new value). `kind` is `config` (`name` is the field and "
        "`detail` is `= <value>`) or `command`; `command_id` is the queue id for both."
    ),
)
async def list_command_log(
    device_id: str | None = None,
    limit: int = Query(COMMAND_LOG_DEFAULT_LIMIT, ge=1, le=COMMAND_LOG_MAX_LIMIT),
    db: Session = Depends(get_db),
    _: User = Depends(current_superuser),
) -> CommandLogResponse:
    query = select(CommandLogEntry).order_by(
        CommandLogEntry.occurred_at.desc(), CommandLogEntry.id.desc()
    )
    if device_id is not None:
        query = query.where(CommandLogEntry.device_id == device_id)

    rows = db.scalars(query.limit(limit)).all()
    return CommandLogResponse(
        entries=[
            CommandLogItem(
                id=row.id,
                occurred_at=row.occurred_at.isoformat(),
                device_id=row.device_id,
                direction=row.direction,
                kind=row.kind,
                name=row.name,
                command_id=row.command_id,
                status=row.status,
                detail=row.detail,
            )
            for row in rows
        ]
    )


async def _command_ack_event_stream(
    subscription: Subscription, keepalive_s: float = _COMMAND_ACK_KEEPALIVE_INTERVAL_S
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


@stream_router.get(
    "/commands/stream",
    response_class=StreamingResponse,
    summary="Stream a signal for each one-shot command a device acknowledges",
    description=(
        "Server-Sent Events (`text/event-stream`), held open. Emits a `command_ack` event "
        "with `device_id`, `command_id`, `command`, `status` and `error` for every terminal "
        "acknowledgement as it is processed, so the dashboard shows the result at once "
        "instead of noticing that the item vanished from the queue. Requires a superuser "
        "token; device credentials are not accepted. The native `EventSource` cannot send the "
        "`Authorization` header, so clients use `fetch()` and read the response body as a "
        "stream; never put the token in the URL. The stream is not scoped to one device, "
        "because a client queuing a command does not know in advance which device's "
        "acknowledgement will land first. Its mechanics (`: connected` on open, `: keep-alive` "
        "after 20 seconds of silence, the oldest pending event dropped when a subscriber's "
        "queue is full, no replay after a reconnect, in-memory subscribers of one server "
        "process) are those of `GET /measurements/stream`. Errors: 401, 403 for a "
        "non-superuser, 429 when the per-user (5) or global (100) limit of concurrent streams "
        "is reached."
    ),
)
async def stream_command_ack_events(
    user: User = Depends(current_superuser),
) -> StreamingResponse:
    try:
        subscription = command_ack_broadcaster.subscribe(user.id)
    except StreamLimitExceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many open streams"
        ) from None

    return StreamingResponse(
        _command_ack_event_stream(subscription),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
