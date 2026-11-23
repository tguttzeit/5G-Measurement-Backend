"""SQLAlchemy model for measurement campaigns."""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Campaign(Base):
    """A named group of runs that measurements are scoped to on the public map.

    Membership is explicit: a run belongs to a campaign through `Run.campaign_id`. The campaign's
    period is not stored but derived from the timestamps of its runs' measurements.
    """

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
