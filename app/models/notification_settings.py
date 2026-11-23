"""SQLAlchemy model for a user's opt-in push-notification preferences."""

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserNotificationSettings(Base):
    """One row per user, created on their first read or save of the notification settings.

    `topic` is the secret that routes messages to the user's ntfy subscription. It is stable
    until the user regenerates it, including while notifications are disabled.
    """

    __tablename__ = "user_notification_settings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    topic: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    events: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
