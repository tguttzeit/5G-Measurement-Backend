"""Database model for queued device config overrides and one-shot commands."""
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CommandType(StrEnum):
    """Discriminator for the two kinds of row `device_commands` holds."""

    CONFIG_OVERRIDE = "config_override"
    ONE_SHOT = "one_shot"


class DeviceCommand(Base):
    """A queued config override or one-shot command for a device.

    Config overrides are upserted per (device_id, field): a new POST for a field that
    already has an active override replaces its value rather than adding a second row, so
    the override stays a single current-state entry that's included in every heartbeat
    response until explicitly changed. One-shot commands get a fresh row per queue request,
    are delivered at-least-once (redelivered on every heartbeat until removed or expired),
    and are deduped device-side by `id` rather than by the backend tracking acknowledgement.
    """

    __tablename__ = "device_commands"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("devices.device_id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[CommandType] = mapped_column(
        SQLEnum(CommandType, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
        index=True,
    )
    # The overridden field name for CONFIG_OVERRIDE rows; NULL for ONE_SHOT rows.
    field: Mapped[str | None] = mapped_column(String, nullable=True)
    # {"value": ...} for CONFIG_OVERRIDE, {"command": "force-upload-now"} for ONE_SHOT.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Set (and reset) on every heartbeat that includes this row - informational only, since
    # at-least-once delivery means it does not stop redelivery on its own.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # TTL for ONE_SHOT rows (default 24h, set at creation); NULL for CONFIG_OVERRIDE rows,
    # which have no expiry and stay in effect until replaced or deleted.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_device_commands_device_type", "device_id", "type"),
    )


class CommandLogEntry(Base):
    """Append-only record of one communication event about a config override or one-shot command:
    queued by a maintainer, or acknowledged by the device. Unlike `device_commands`, rows here are
    never cleared by acks or the queue's TTL.
    """

    __tablename__ = "command_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # "to_device" (queued by a maintainer) or "from_device" (acknowledged by the device).
    direction: Mapped[str] = mapped_column(String, nullable=False)
    # "config" or "command".
    kind: Mapped[str] = mapped_column(String, nullable=False)
    # The overridden field name for config rows, the command name for command rows.
    name: Mapped[str] = mapped_column(String, nullable=False)
    # `device_commands.id` of the command/override this event is about. Deliberately not a
    # foreign key: the queue row is deleted on ack while this record has to outlive it.
    command_id: Mapped[int | None] = mapped_column(nullable=True)
    # to_device rows: "queued", "delivered" (first heartbeat that carried it) or "removed" (a
    # maintainer deleted it from the queue). from_device rows: the device-reported ack status.
    status: Mapped[str] = mapped_column(String, nullable=False)
    # The override value ("= 5") for queued config rows, the device's error text for acks.
    detail: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_command_log_device_occurred", "device_id", "occurred_at"),
        Index("ix_command_log_occurred", "occurred_at"),
    )


class CommandStatusDismissal(Base):
    """A maintainer's "Delete shown" on a finished command of the command status timelines.

    Only hides the command from `GET /devices/{id}/command-status`: `command_log` and the
    Command Communication view stay complete.
    Activity on the command after `dismissed_at` makes it show up again.
    """

    __tablename__ = "command_status_dismissals"

    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("devices.device_id", ondelete="CASCADE"), primary_key=True
    )
    # `device_commands.id`; like `command_log.command_id` not a foreign key, the queue row is
    # long gone for a finished command.
    command_id: Mapped[int] = mapped_column(primary_key=True)
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CommandLogDirection(StrEnum):
    TO_DEVICE = "to_device"
    FROM_DEVICE = "from_device"


__all__ = [
    "CommandLogDirection",
    "CommandLogEntry",
    "CommandStatusDismissal",
    "CommandType",
    "DeviceCommand",
]
