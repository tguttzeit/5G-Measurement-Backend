"""SQLAlchemy model for latency test results."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LatencyTestResult(Base):
    """Latency test result (flent baseline/under-load run) stored in the database.

    `start_fix`/`end_fix` are kept as JSONB rather than flattened columns: unlike
    `Measurement`, nothing here needs to be queried by position yet, so the full nested
    GNSSFix objects are stored as-is for fidelity.
    """

    __tablename__ = "latency_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    device_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    flent_test: Mapped[str] = mapped_column(String(255), nullable=False)

    run_pk: Mapped[int] = mapped_column(
        Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    start_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    start_fix: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    end_fix: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    baseline_rtt_ms: Mapped[float | None] = mapped_column(Float)
    rtt_under_load_ms: Mapped[float | None] = mapped_column(Float)
    rtt_p99_ms: Mapped[float | None] = mapped_column(Float)
    download_mbits_s: Mapped[float | None] = mapped_column(Float)
    upload_mbits_s: Mapped[float | None] = mapped_column(Float)

    # Client-generated dedup key. Nullable since older device builds don't send
    # one yet; a unique constraint still works with that - Postgres treats every NULL in a
    # unique index as distinct from every other NULL, so rows without a key never collide.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_latency_results_device_timestamp", "device_id", "start_timestamp"),
        UniqueConstraint(
            "device_id", "idempotency_key", name="uq_latency_results_device_idempotency_key"
        ),
    )
