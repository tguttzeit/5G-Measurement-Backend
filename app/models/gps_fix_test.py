"""Database model for the live GPS-fix-finding diagnostic run."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GpsFixTestStatus(Base):
    """The single latest gps-fix-test status report for a device.

    One row per device_id (upserted on every device push) - this is a live-only view, not a
    stored time series, so there is no history to keep. Overwritten wholesale on every
    `POST /devices/{device_id}/gps-fix-test/status`; staleness is determined at read time by
    comparing `updated_at` against a cutoff (see app/routers/gps_fix_test.py), not by deleting
    the row when a run ends.
    """

    __tablename__ = "gps_fix_test_status"

    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("devices.device_id", ondelete="CASCADE"), primary_key=True
    )
    num_satellites: Mapped[int] = mapped_column(Integer, nullable=False)
    has_fix: Mapped[bool] = mapped_column(Boolean, nullable=False)
    elapsed_s: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


__all__ = ["GpsFixTestStatus"]
