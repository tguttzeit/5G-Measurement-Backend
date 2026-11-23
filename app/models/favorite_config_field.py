"""SQLAlchemy model for a user's favorite Remote Configuration fields."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserFavoriteConfigField(Base):
    """One field a user marked as favorite; the composite key makes a field unique per user.

    `field_key` is not a foreign key: the fields live in the registry in code
    (`app.config_override_spec`), so a field removed from it leaves a row that is ignored.
    """

    __tablename__ = "user_favorite_config_fields"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    field_key: Mapped[str] = mapped_column(String(100), primary_key=True)
