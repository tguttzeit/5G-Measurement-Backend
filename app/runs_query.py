"""Runs list query: the runs table joined with the aggregate of each run's
measurements. A run without measurements (e.g. one that only has latency results) is not listed,
nor is a run in the trash.

A run's start/end are the min/max timestamp of its measurements, so the date filter applies to
the run's start rather than to individual rows - a run belongs to the day it started in. Its
campaign is the one it is assigned to in the `runs` table, if any.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.measurements_query import resolve_optional_campaign_id
from app.models.campaign import Campaign
from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from app.models.run import Run
from app.models.user import User
from app.run_ids import is_legacy_run_id
from app.schemas.run import Run as RunSchema
from app.schemas.run import RunSortKey, SortOrder, TrashedRun

MAX_PAGE_SIZE = 100

_START = func.min(Measurement.timestamp)
_END = func.max(Measurement.timestamp)
_POINT_COUNT = func.count()

_SORT_EXPRESSIONS: dict[RunSortKey, ColumnElement] = {
    RunSortKey.START: _START,
    RunSortKey.DURATION: _END - _START,
    RunSortKey.POINT_COUNT: _POINT_COUNT,
}


@dataclass(frozen=True)
class RunPage:
    runs: list[RunSchema]
    total: int


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def query_runs(
    db: Session,
    page: int,
    page_size: int,
    sort: RunSortKey = RunSortKey.START,
    order: SortOrder = SortOrder.DESC,
    device_id: str | None = None,
    mission_type: str | None = None,
    campaign_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    unassigned: bool = False,
) -> RunPage:
    """One page of runs. `date_from`/`date_to` are inclusive UTC calendar days of the run start;
    `campaign_id` keeps the runs assigned to that campaign (404 if it does not exist, see
    `resolve_optional_campaign_id`), `unassigned` those assigned to none - the two exclude each
    other."""
    if unassigned and campaign_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="campaign_id and unassigned cannot be combined",
        )
    scoped_campaign_id = resolve_optional_campaign_id(db, campaign_id)

    row_conditions = [Run.deleted_at.is_(None)]
    if scoped_campaign_id is not None:
        row_conditions.append(Run.campaign_id == scoped_campaign_id)
    if unassigned:
        row_conditions.append(Run.campaign_id.is_(None))
    if device_id is not None:
        row_conditions.append(Run.device_id == device_id)
    if mission_type is not None:
        row_conditions.append(Run.mission_type == mission_type)

    run_conditions = []
    if date_from is not None:
        run_conditions.append(_START >= _day_start(date_from))
    if date_to is not None:
        run_conditions.append(_START < _day_start(date_to + timedelta(days=1)))

    runs = (
        select(
            Run.id,
            Run.device_id,
            Run.run_id,
            Run.name,
            Run.mission_type,
            _START.label("start"),
            _END.label("end"),
            _POINT_COUNT.label("point_count"),
            func.avg(Measurement.rsrp).label("mean_rsrp"),
            func.avg(Measurement.rsrq).label("mean_rsrq"),
            func.avg(Measurement.sinr).label("mean_sinr"),
            Run.campaign_id,
            Campaign.name.label("campaign_name"),
        )
        .join_from(Run, Measurement, Measurement.run_pk == Run.id)
        .outerjoin(Campaign, Campaign.id == Run.campaign_id)
        .where(*row_conditions)
        .group_by(Run.id, Campaign.name)
        .having(*run_conditions)
    )

    total = db.scalar(select(func.count()).select_from(runs.subquery())) or 0

    sort_expression = _SORT_EXPRESSIONS[sort]
    direction = sort_expression.asc() if order == SortOrder.ASC else sort_expression.desc()
    rows = db.execute(
        runs.order_by(direction, Run.device_id, Run.run_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return RunPage(runs=[_to_run(row) for row in rows], total=total)


def _to_run(row) -> RunSchema:
    return RunSchema(
        id=row.id,
        name=row.name,
        run_id=row.run_id,
        device_id=row.device_id,
        mission_type=row.mission_type,
        start=row.start,
        end=row.end,
        point_count=row.point_count,
        mean_rsrp=row.mean_rsrp,
        mean_rsrq=row.mean_rsrq,
        mean_sinr=row.mean_sinr,
        campaign_id=row.campaign_id,
        campaign_name=row.campaign_name,
        legacy=is_legacy_run_id(row.run_id),
    )


@dataclass(frozen=True)
class TrashedRunPage:
    runs: list[TrashedRun]
    total: int


def query_trashed_runs(db: Session, page: int, page_size: int) -> TrashedRunPage:
    """One page of the runs in the trash, most recently trashed first. Unlike `query_runs`, runs
    without measurements are listed too, so everything in the trash can be restored or deleted."""
    measurements = (
        select(
            Measurement.run_pk,
            func.min(Measurement.timestamp).label("start"),
            func.max(Measurement.timestamp).label("end"),
            func.count().label("point_count"),
        )
        .group_by(Measurement.run_pk)
        .subquery()
    )
    latency_results = (
        select(LatencyTestResult.run_pk, func.count().label("latency_result_count"))
        .group_by(LatencyTestResult.run_pk)
        .subquery()
    )
    is_trashed = Run.deleted_at.isnot(None)

    total = db.scalar(select(func.count()).select_from(Run).where(is_trashed)) or 0
    rows = db.execute(
        select(
            Run,
            Campaign.name.label("campaign_name"),
            User.email.label("deleted_by_email"),
            measurements.c.start,
            measurements.c.end,
            func.coalesce(measurements.c.point_count, 0).label("point_count"),
            func.coalesce(latency_results.c.latency_result_count, 0).label(
                "latency_result_count"
            ),
        )
        .outerjoin(Campaign, Campaign.id == Run.campaign_id)
        .outerjoin(User, User.id == Run.deleted_by)
        .outerjoin(measurements, measurements.c.run_pk == Run.id)
        .outerjoin(latency_results, latency_results.c.run_pk == Run.id)
        .where(is_trashed)
        .order_by(Run.deleted_at.desc(), Run.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return TrashedRunPage(runs=[_to_trashed_run(row) for row in rows], total=total)


def _to_trashed_run(row) -> TrashedRun:
    run = row.Run
    return TrashedRun(
        id=run.id,
        name=run.name,
        run_id=run.run_id,
        device_id=run.device_id,
        mission_type=run.mission_type,
        start=row.start,
        end=row.end,
        point_count=row.point_count,
        latency_result_count=row.latency_result_count,
        campaign_id=run.campaign_id,
        campaign_name=row.campaign_name,
        legacy=is_legacy_run_id(run.run_id),
        deleted_at=run.deleted_at,
        deleted_by=run.deleted_by,
        deleted_by_email=row.deleted_by_email,
    )
