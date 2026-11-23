"""Builds the per-command lifecycle shown on the Remote Configuration page from
`device_commands` (what is still queued) and `command_log` (what happened to each command,
including after its queue row was cleared by an ack).
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CommandLogDirection,
    CommandLogEntry,
    CommandType,
    DeviceCommand,
    Heartbeat,
)
from app.schemas.commands import OneShotCommand
from app.schemas.settings import ShutdownConfirmation

# shutdown-now's "received" is as final as it ever gets - the device is off, there is no later
# heartbeat that could report "success". reboot-now turned out to behave differently in
# practice: the device sends
# "received" when it gets the command, then a separate "success" once it comes back up - two
# heartbeats, not one. So reboot-now's "received" must NOT be terminal, or the backend would
# stop redelivering (and delete the row) before that second ack ever has something to clear.
RECEIVED_IS_TERMINAL_FOR = {OneShotCommand.SHUTDOWN_NOW}

# A shutdown-now never reports a result (the device is off), so its success is inferred instead:
# no heartbeat for the configured silence (default: 4 heartbeat intervals) after the one that
# carried its "received" ack.
DEFAULT_SHUTDOWN_CONFIRMATION = ShutdownConfirmation()
# The device's own default (`interval_s`), used when it doesn't report
# heartbeat_interval_s in current_config.
DEFAULT_HEARTBEAT_INTERVAL_S = 60.0
# A shutdown-now whose device is still sending heartbeats this many heartbeats after its "received"
# ack evidently did not shut down.
SHUTDOWN_FAIL_HEARTBEATS = 10
# How far past the last heartbeat a "received" ack may sit and still count as that heartbeat's
# ack, in heartbeat intervals - an ack from long before a device came back doesn't confirm
# anything about a shutdown now.
_ACK_MAX_AGE_INTERVALS = 2
_ACK_CLOCK_SKEW = timedelta(seconds=5)
_INTERVAL_LOOKBACK_HEARTBEATS = 20
# The ack heartbeat itself is stored a moment after its ack is logged; it must not count as one
# of the heartbeats that came after the ack.
_SAME_HEARTBEAT_SLACK = timedelta(seconds=2)

_RESULT_STATUSES = {"success", "failed", "not_applicable"}


@dataclass
class CommandStatusItem:
    command_id: int
    kind: str
    name: str
    detail: str | None
    in_queue: bool
    queued_at: datetime | None = None
    delivered_at: datetime | None = None
    received_at: datetime | None = None
    result: str | None = None
    result_at: datetime | None = None
    error: str | None = None
    removed_at: datetime | None = None
    promoted_at: datetime | None = None
    expired_at: datetime | None = None
    expires_at: datetime | None = None
    last_activity: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=UTC))

    @property
    def state(self) -> str:
        if self.result is not None:
            return self.result
        if self.promoted_at is not None:
            return "promoted"
        if self.expired_at is not None:
            return "expired"
        if self.removed_at is not None:
            return "removed"
        # Also covers a shutdown-now, whose queue row its "received" ack already cleared.
        if self.received_at is not None:
            return "received"
        if not self.in_queue:
            return "removed"
        if self.expires_at is not None and self.expires_at < datetime.now(UTC):
            return "expired"
        if self.delivered_at is not None:
            return "delivered"
        return "queued"

    @property
    def complete(self) -> bool:
        return self.state in {
            "success",
            "failed",
            "not_applicable",
            "promoted",
            "removed",
            "expired",
        }

    @property
    def finished(self) -> bool:
        """Done and no longer sent to the device. An applied config override is complete too, but
        stays queued (it rides along every heartbeat until replaced), so it is not finished."""
        return self.complete and not self.in_queue

    def is_dismissed(self, dismissed_at: datetime | None) -> bool:
        """Whether a "Delete shown" at `dismissed_at` hides this item. Activity after it (a
        re-queued command restarts its lifecycle) shows the item again."""
        return dismissed_at is not None and self.finished and self.last_activity <= dismissed_at


def build_command_status(
    queue_rows: list[DeviceCommand],
    log_rows: list[CommandLogEntry],
    limit: int,
    dismissed_at: Mapping[int, datetime] | None = None,
) -> list[CommandStatusItem]:
    """Newest-activity-first lifecycle per command id, at most `limit` items.

    `dismissed_at` maps command ids to when a maintainer deleted them from the view; those are
    left out before `limit` is applied, so they do not use up slots.

    A command id's events are only read from its latest "queued" event onward: re-queueing a
    config override reuses its row (and id), which restarts its lifecycle.
    """
    queue_by_id = {row.id: row for row in queue_rows}
    events_by_id: dict[int, list[CommandLogEntry]] = {}
    for entry in sorted(log_rows, key=lambda e: (e.occurred_at, e.id)):
        if entry.command_id is not None:
            events_by_id.setdefault(entry.command_id, []).append(entry)

    items = []
    for command_id in queue_by_id.keys() | events_by_id.keys():
        events = events_by_id.get(command_id, [])
        queued_indexes = [i for i, e in enumerate(events) if e.status == "queued"]
        if queued_indexes:
            events = events[queued_indexes[-1] :]

        row = queue_by_id.get(command_id)
        if row is not None:
            is_config = row.type == CommandType.CONFIG_OVERRIDE
            kind = "config" if is_config else "command"
            name = row.field if is_config else row.payload["command"]
            detail = f"= {row.payload['value']}" if is_config else None
        else:
            kind, name, detail = events[0].kind, events[0].name, events[0].detail

        item = CommandStatusItem(
            command_id=command_id,
            kind=kind,
            name=name,
            detail=detail,
            in_queue=row is not None,
            queued_at=row.created_at if row is not None and not queued_indexes else None,
            expires_at=row.expires_at if row is not None else None,
        )
        for event in events:
            if event.status == "queued":
                item.queued_at = event.occurred_at
            elif event.status == "delivered" and item.delivered_at is None:
                item.delivered_at = event.occurred_at
            elif event.status == "removed":
                item.removed_at = event.occurred_at
            elif event.status == "promoted":
                item.promoted_at = event.occurred_at
            elif event.status == "expired":
                item.expired_at = event.occurred_at
            elif event.direction == "from_device":
                if event.status == "received" and item.received_at is None:
                    item.received_at = event.occurred_at
                elif event.status in _RESULT_STATUSES and item.result is None:
                    item.result, item.result_at = event.status, event.occurred_at
                    # An inferred shutdown success carries its reason as detail; that stays in
                    # the log but is not an error.
                    if event.status != "success":
                        item.error = event.detail
        stamps = [
            t
            for t in (
                item.queued_at,
                item.delivered_at,
                item.received_at,
                item.result_at,
                item.removed_at,
                item.promoted_at,
                item.expired_at,
            )
            if t
        ]
        item.last_activity = max(stamps) if stamps else item.last_activity
        if row is not None and row.delivered_at is not None and item.delivered_at is None:
            # Delivered before the log existed (or logged elsewhere): the queue row still knows.
            item.delivered_at = row.delivered_at
        if not item.is_dismissed((dismissed_at or {}).get(command_id)):
            items.append(item)

    items.sort(key=lambda i: (i.last_activity, i.command_id), reverse=True)
    return items[:limit]


def device_heartbeat_interval_s(db: Session, device_id: str) -> float:
    """The interval the device last reported, from its most recent heartbeats that carried a
    current_config (an older-build heartbeat may not have one)."""
    recent_configs = db.scalars(
        select(Heartbeat.current_config)
        .where(Heartbeat.device_id == device_id)
        .order_by(Heartbeat.received_at.desc())
        .limit(_INTERVAL_LOOKBACK_HEARTBEATS)
    ).all()
    for current_config in recent_configs:
        reported = current_config.get("heartbeat_interval_s") if current_config else None
        if isinstance(reported, int | float) and not isinstance(reported, bool) and reported > 0:
            return float(reported)
    return DEFAULT_HEARTBEAT_INTERVAL_S


def _unresolved_shutdown_acks(db: Session, device_id: str) -> list[CommandLogEntry]:
    """The "received" acks of shutdown-now commands that have no result (yet)."""
    acks = db.scalars(
        select(CommandLogEntry).where(
            CommandLogEntry.device_id == device_id,
            CommandLogEntry.direction == CommandLogDirection.FROM_DEVICE,
            CommandLogEntry.kind == "command",
            CommandLogEntry.name == "shutdown-now",
            CommandLogEntry.status == "received",
        )
    ).all()
    return [
        ack
        for ack in acks
        if db.scalars(
            select(CommandLogEntry.id)
            .where(
                CommandLogEntry.command_id == ack.command_id,
                CommandLogEntry.direction == CommandLogDirection.FROM_DEVICE,
                CommandLogEntry.status.in_(_RESULT_STATUSES),
                CommandLogEntry.occurred_at >= ack.occurred_at,
            )
            .limit(1)
        ).first()
        is None
    ]


def required_silence(confirmation: ShutdownConfirmation, interval_s: float) -> timedelta:
    if confirmation.mode == "seconds":
        return timedelta(seconds=confirmation.seconds)
    return timedelta(seconds=confirmation.intervals * interval_s)


def confirm_shutdowns(
    db: Session,
    device_id: str,
    last_heartbeat_at: datetime,
    interval_s: float,
    now: datetime,
    confirmation: ShutdownConfirmation = DEFAULT_SHUTDOWN_CONFIRMATION,
) -> None:
    """Log a success for each shutdown-now whose device has gone silent.

    Called when the status is read and when a heartbeat arrives after a gap (`last_heartbeat_at`
    is then the heartbeat before it), so a device that was off and came back is still confirmed.
    Idempotent: a shutdown that already has a result is skipped.
    """
    silent_for = required_silence(confirmation, interval_s)
    if now - last_heartbeat_at < silent_for:
        return

    for ack in _unresolved_shutdown_acks(db, device_id):
        if ack.occurred_at > last_heartbeat_at + _ACK_CLOCK_SKEW:
            continue
        if last_heartbeat_at - ack.occurred_at > timedelta(
            seconds=_ACK_MAX_AGE_INTERVALS * interval_s
        ):
            continue
        db.add(
            CommandLogEntry(
                device_id=device_id,
                direction=CommandLogDirection.FROM_DEVICE,
                kind="command",
                name="shutdown-now",
                command_id=ack.command_id,
                status="success",
                detail=(
                    f"no heartbeat for {confirmation.intervals} intervals"
                    if confirmation.mode == "intervals"
                    else f"no heartbeat for {confirmation.seconds:g} s"
                ),
                occurred_at=last_heartbeat_at + silent_for,
            )
        )


def record_reported_shutdown_successes(
    db: Session, device_id: str, command_ids: Iterable[int]
) -> list[int]:
    """Log the device's own success for each listed shutdown-now that is still unresolved.

    After a shutdown the device acks the command as success on its next boot. The "received" ack
    already cleared the queue row, so this is matched against the command log instead: only a
    shutdown-now of this device with a logged "received" and no result counts. Returns the ids
    that were logged.
    """
    unresolved = {ack.command_id for ack in _unresolved_shutdown_acks(db, device_id)}
    resolved = [command_id for command_id in dict.fromkeys(command_ids) if command_id in unresolved]
    for command_id in resolved:
        db.add(
            CommandLogEntry(
                device_id=device_id,
                direction=CommandLogDirection.FROM_DEVICE,
                kind="command",
                name="shutdown-now",
                command_id=command_id,
                status="success",
            )
        )
    return resolved


def fail_unresponsive_shutdowns(db: Session, device_id: str) -> None:
    """Log a failure for each shutdown-now whose device kept sending heartbeats after its ack.

    Called on every heartbeat, after the new heartbeat was flushed so it counts.
    """
    for ack in _unresolved_shutdown_acks(db, device_id):
        heartbeats_since = db.scalar(
            select(func.count())
            .select_from(Heartbeat)
            .where(
                Heartbeat.device_id == device_id,
                Heartbeat.received_at > ack.occurred_at + _SAME_HEARTBEAT_SLACK,
            )
        )
        if heartbeats_since >= SHUTDOWN_FAIL_HEARTBEATS:
            db.add(
                CommandLogEntry(
                    device_id=device_id,
                    direction=CommandLogDirection.FROM_DEVICE,
                    kind="command",
                    name="shutdown-now",
                    command_id=ack.command_id,
                    status="failed",
                    detail=(
                        f"device still sending heartbeats {SHUTDOWN_FAIL_HEARTBEATS} heartbeats "
                        "after acknowledging the shutdown"
                    ),
                )
            )
