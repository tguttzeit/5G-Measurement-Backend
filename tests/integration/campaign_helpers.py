"""Test-data helpers for campaigns, which consist of the runs assigned to them.

`assign_runs` is the explicit form. `date_window_campaign` is a fixture shortcut for tests that
only care which rows end up in a campaign: it registers a date window with the session, and from
then on every commit on that session assigns each run to the
first window containing the UTC day of the run's first row. It only builds fixture state - the
code under test sees nothing but runs with a `campaign_id`.
"""

from datetime import UTC, date, datetime

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from app.models.run import Run

_WINDOWS_KEY = "campaign_date_windows"


def create_campaign(db_session: Session, name: str) -> Campaign:
    campaign = Campaign(name=name)
    db_session.add(campaign)
    db_session.commit()
    db_session.refresh(campaign)
    return campaign


def assign_runs(db_session: Session, campaign: Campaign, *runs: tuple[str, str]) -> None:
    """Assign the given (device_id, run_id) pairs to the campaign, creating missing runs."""
    for device_id, run_id in runs:
        run = db_session.scalar(
            select(Run).where(Run.device_id == device_id, Run.run_id == run_id)
        )
        if run is None:
            run = Run(device_id=device_id, run_id=run_id, mission_type="ground")
            db_session.add(run)
        run.campaign_id = campaign.id
    db_session.commit()


def date_window_campaign(
    db_session: Session, name: str, start_date: date, end_date: date
) -> Campaign:
    campaign = create_campaign(db_session, name)
    windows = db_session.info.get(_WINDOWS_KEY)
    if windows is None:
        windows = db_session.info[_WINDOWS_KEY] = []
        event.listen(db_session, "before_commit", _assign_runs_to_windows)
    windows.append((campaign.id, start_date, end_date))
    _assign_runs_to_windows(db_session)
    db_session.commit()
    db_session.refresh(campaign)
    return campaign


def _run_starts(db_session: Session) -> dict[int, datetime]:
    starts: dict[int, datetime] = {}
    sources = (
        (Measurement.run_pk, func.min(Measurement.timestamp)),
        (LatencyTestResult.run_pk, func.min(LatencyTestResult.start_timestamp)),
    )
    for run_column, start in sources:
        for run_pk, timestamp in db_session.execute(select(run_column, start).group_by(run_column)):
            starts[run_pk] = min(timestamp, starts.get(run_pk, timestamp))
    return starts


def _assign_runs_to_windows(db_session: Session) -> None:
    db_session.flush()
    windows = db_session.info[_WINDOWS_KEY]
    runs = {run.id: run for run in db_session.scalars(select(Run))}
    for run_pk, start in _run_starts(db_session).items():
        day = start.astimezone(UTC).date()
        runs[run_pk].campaign_id = next(
            (campaign_id for campaign_id, first, last in windows if first <= day <= last), None
        )
    db_session.flush()
