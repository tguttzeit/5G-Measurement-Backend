"""SQLAlchemy model for measurement runs."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.run_ids import RUN_ID_COLUMN_LENGTH

RUN_NAME_MAX_LENGTH = 255


class Run(Base):
    """One drive/flight of one device, identified by the device-supplied (device_id, run_id).

    `measurements` and `latency_results` reference a run through their `run_pk` foreign key
    (`ON DELETE CASCADE`). `(device_id, run_id)` only matches uploads to their run and is never
    edited; `name`, `mission_type` and `campaign_id` are the editable attributes. A run belongs to
    at most one campaign; without one it is "unassigned". Like `Measurement.device_id`,
    `device_id` is deliberately not a foreign key to `devices`, so runs of a since-removed device
    stay intact.

    A run with `deleted_at` set is in the trash: every read path treats it and its data as
    absent, but uploads still attach to it (it stays in the trash), and a superuser can restore
    it or delete it permanently. `deleted_by` is the id of the user who moved it there.
    """

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(RUN_ID_COLUMN_LENGTH), nullable=False)
    name: Mapped[str | None] = mapped_column(String(RUN_NAME_MAX_LENGTH), nullable=True)
    mission_type: Mapped[str] = mapped_column(String(255), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (UniqueConstraint("device_id", "run_id", name="uq_runs_device_run"),)
