"""Campaign listing with the period derived from each campaign's runs.

A campaign stores only its name. Its period runs from the first measurement of its oldest run to
the last measurement of its newest run - i.e. the earliest and latest measurement timestamp over
all runs assigned to it, reported as UTC days - and is empty (None) while no run is assigned.
Runs in the trash do not count.
"""

from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.campaign import Campaign as CampaignModel
from app.models.measurement import Measurement
from app.models.run import Run
from app.schemas.campaign import Campaign

_PERIOD_START = func.min(Measurement.timestamp)
_PERIOD_END = func.max(Measurement.timestamp)


def _utc_day(timestamp: datetime | None):
    return timestamp.astimezone(UTC).date() if timestamp is not None else None


def _campaigns_with_period(db: Session, campaign_id: int | None = None) -> list[Campaign]:
    query = (
        select(
            CampaignModel.id,
            CampaignModel.name,
            _PERIOD_START.label("start"),
            _PERIOD_END.label("end"),
        )
        .outerjoin(Run, and_(Run.campaign_id == CampaignModel.id, Run.deleted_at.is_(None)))
        .outerjoin(Measurement, Measurement.run_pk == Run.id)
        .group_by(CampaignModel.id, CampaignModel.name)
        .order_by(_PERIOD_START.asc().nulls_last(), CampaignModel.name)
    )
    if campaign_id is not None:
        query = query.where(CampaignModel.id == campaign_id)

    return [
        Campaign(id=row.id, name=row.name, start=_utc_day(row.start), end=_utc_day(row.end))
        for row in db.execute(query)
    ]


def list_campaigns(db: Session) -> list[Campaign]:
    """All campaigns, oldest period first; campaigns without runs come last."""
    return _campaigns_with_period(db)


def get_campaign(db: Session, campaign_id: int) -> Campaign | None:
    campaigns = _campaigns_with_period(db, campaign_id)
    return campaigns[0] if campaigns else None
