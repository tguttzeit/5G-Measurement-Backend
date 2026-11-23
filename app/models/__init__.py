from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.app_setting import AppSetting
from app.models.campaign import Campaign
from app.models.commands import (
    CommandLogDirection,
    CommandLogEntry,
    CommandStatusDismissal,
    CommandType,
    DeviceCommand,
)
from app.models.favorite_config_field import UserFavoriteConfigField
from app.models.gps_fix_test import GpsFixTestStatus
from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from app.models.notification_settings import UserNotificationSettings
from app.models.run import Run
from app.models.testing import TestResult, TestStatus, TestType
from app.models.user import User


class Device(Base):
    """Represents a registered device that can send heartbeats."""

    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    api_key_hash: Mapped[str] = mapped_column(String, nullable=False)
    # Distinct from api_key_hash: this is stored in recoverable (plaintext) form, since HMAC
    # signing of heartbeat responses requires the actual secret bytes, not a one-way hash of
    # them. Kept as a separate secret so a leak of one can't be used to forge the other
    # direction (device->server auth vs. server->device response authenticity).
    hmac_secret: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    heartbeats: Mapped[list["Heartbeat"]] = relationship(
        "Heartbeat", back_populates="device", cascade="all, delete-orphan"
    )


class Heartbeat(Base):
    """Represents a heartbeat received from a device."""

    __tablename__ = "heartbeats"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("devices.device_id", ondelete="CASCADE"), index=True, nullable=False
    )
    received_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Datapoint tallies (cumulative since run start)
    datapoints_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    datapoints_valid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    datapoints_invalid: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Pipeline state
    pipeline_broken: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Storage stats
    storage_pending_files: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_disk_free_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Device's live in-effect config values, keyed by ConfigOverrideCreate's field names
    #; latest-per-device only, matching the rest of this table - no historical
    # tracking.
    current_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Run phase - one of RunPhase's fixed values, enforced at the schema layer;
    # stored as plain text since the column itself doesn't need to enforce the enum.
    run_phase: Mapped[str | None] = mapped_column(String, nullable=True)
    # GPS-fix status: {has_fix, num_satellites, fix_age_s}. Small, fixed-shape
    # object - a JSON column here follows current_config's precedent above rather than adding
    # three more flat columns for one grouped concept.
    gps_fix: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {fingerprint, same_error_count, consecutive_reboots, action} of a critical_error
    # heartbeat; same JSON-column precedent as gps_fix.
    critical_error: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    device: Mapped[Device] = relationship("Device", back_populates="heartbeats")

    __table_args__ = (
        Index("ix_heartbeats_device_received", "device_id", "received_at"),
    )


__all__ = [
    "AppSetting",
    "Campaign",
    "Device",
    "Heartbeat",
    "CommandLogDirection",
    "CommandLogEntry",
    "CommandStatusDismissal",
    "CommandType",
    "DeviceCommand",
    "GpsFixTestStatus",
    "LatencyTestResult",
    "Measurement",
    "Run",
    "User",
    "UserFavoriteConfigField",
    "UserNotificationSettings",
    "TestResult",
    "TestStatus",
    "TestType",
]
