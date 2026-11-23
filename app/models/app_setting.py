"""SQLAlchemy model for persisted, runtime-changeable application settings."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AppSetting(Base):
    """One generic key/value setting; no row means the setting's built-in default applies.

    `value` is stored as JSON so each setting can pick its own shape (an int, a null, a small
    object). It is validated by the typed accessors in `app.app_settings`, not by the column.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(63), primary_key=True)
    value: Mapped[object] = mapped_column(JSON(none_as_null=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
