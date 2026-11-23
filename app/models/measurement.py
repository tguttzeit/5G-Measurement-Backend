"""SQLAlchemy models for measurement data."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Measurement(Base):
    """Measurement datapoint stored in the database.
    
    Flattens the fields that the map/heatmap page will query into indexed columns,
    plus a JSONB column with the full original object for fidelity.
    """
    
    __tablename__ = "measurements"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Flattened fields for efficient querying by map/heatmap
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # One run = one drive/flight of one device. The run owns the mission type and the
    # device-supplied run_id; deleting the run deletes its measurements.
    run_pk: Mapped[int] = mapped_column(
        Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # GNSS fix fields
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    placeholder: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Cell sample fields
    rsrp: Mapped[float | None] = mapped_column(Float)
    rsrq: Mapped[float | None] = mapped_column(Float)
    sinr: Mapped[float | None] = mapped_column(Float)
    rat: Mapped[str | None] = mapped_column(String(50))
    
    # Full original datapoint for fidelity and future-proofing
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    
    # Indexes for common query patterns
    __table_args__ = (
        Index('idx_measurements_device_timestamp', 'device_id', 'timestamp'),
        Index('idx_measurements_geo', 'latitude', 'longitude'),
        Index('idx_measurements_quality', 'rsrp', 'rsrq', 'sinr'),
    )
