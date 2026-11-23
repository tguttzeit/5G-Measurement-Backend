"""Router for runs. Listing is open to any logged-in user, the same auth level as the
authenticated map endpoints; editing and deleting and the trash are
superuser-only. Deleting a run moves it to the trash; only deleting it from there is permanent,
because the backend holds the only copy of the data once a device has uploaded it. Registered
without an `/api` prefix, like every other router here: the dev proxy and Caddy strip it before
forwarding."""

import logging
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_active_user, current_superuser
from app.db import get_db
from app.models.campaign import Campaign
from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from app.models.run import Run
from app.models.user import User
from app.runs_query import MAX_PAGE_SIZE, query_runs, query_trashed_runs
from app.schemas.run import (
    RunAttributes,
    RunBulkUpdate,
    RunBulkUpdateResponse,
    RunChanges,
    RunListResponse,
    RunSortKey,
    SortOrder,
    TrashedRunListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])

_NOT_TRASHED = Run.deleted_at.is_(None)
_TRASHED = Run.deleted_at.isnot(None)


@router.get(
    "",
    response_model=RunListResponse,
    dependencies=[Depends(current_active_user)],
    summary="List runs",
    description=(
        "A run is one drive or flight of one device. Devices send a `run_id` with every "
        "uploaded datapoint and latency result; data without one belongs to a synthetic "
        "`legacy-<device_id>-<mission_type>-<YYYY-MM-DD>` run. Runs are identified by "
        "`(device_id, run_id)`; each has an internal `id` for the edit, delete and trash "
        "endpoints. The stored attributes (`name`, `mission_type`, `campaign_id`) win over "
        "uploads: a later upload for an existing run never overwrites them.\n\n"
        "Requires a logged-in user (any account). A run without any measurement, for example "
        "one that only has latency results, is not listed, nor is a run in the trash. A run's "
        "`start` and `end` are its earliest and latest measurement timestamp, so the date "
        "filters apply to the run's start: a run belongs to the day it started in. A run's "
        "campaign is the one it is explicitly assigned to, independent of its timestamps. "
        "`run_id` is never exposed by a public endpoint.\n\n"
        "Ties in the sort key are broken by `device_id`, then `run_id`, so pages are stable. "
        "Errors: 400 for `campaign_id` together with `unassigned`, 401 without a valid token, "
        "404 for an unknown `campaign_id`, 422 for an invalid parameter."
    ),
)
def list_runs(
    device_id: str | None = Query(None, description="Only this device's runs"),
    mission_type: str | None = Query(None, description="Only runs of this mission type"),
    campaign_id: int | None = Query(
        None, description="Only runs assigned to this campaign; 404 if it does not exist"
    ),
    unassigned: bool = Query(
        False,
        description="Only runs that are assigned to no campaign, for picking runs to add to "
        "one; 400 together with `campaign_id`",
    ),
    date_from: date | None = Query(
        None, alias="from", description="Only runs that started on or after this UTC date"
    ),
    date_to: date | None = Query(
        None, alias="to", description="Only runs that started on or before this UTC date"
    ),
    sort: RunSortKey = Query(RunSortKey.START, description="Sort key"),
    order: SortOrder = Query(SortOrder.DESC, description="Sort direction"),
    page: int = Query(1, ge=1, description="Page number, from 1"),
    page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE, description="Runs per page"),
    db: Session = Depends(get_db),
) -> RunListResponse:
    """Measurement runs (one drive/flight of one device), aggregated from their measurements."""
    result = query_runs(
        db,
        page,
        page_size,
        sort,
        order,
        device_id,
        mission_type,
        campaign_id,
        date_from,
        date_to,
        unassigned,
    )
    return RunListResponse(runs=result.runs, total=result.total, page=page, page_size=page_size)


def _run_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")


def _raise_if_campaign_missing(db: Session, changes: RunChanges) -> None:
    campaign_id = changes.campaign_id
    if campaign_id is not None and db.get(Campaign, campaign_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")


def _apply(db: Session, run_pks: list[int], changes: RunChanges) -> None:
    """One UPDATE for all runs, committed at once. A run deleted or trashed since the existence
    check leaves the row count short, a campaign deleted since it trips the foreign key; either way
    nothing is changed and the request fails with 404."""
    try:
        result = db.execute(
            update(Run).where(Run.id.in_(run_pks), _NOT_TRASHED).values(**changes.as_values())
        )
        if result.rowcount != len(run_pks):
            db.rollback()
            raise _run_not_found()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        ) from None


@router.patch(
    "/{run_pk}",
    response_model=RunAttributes,
    dependencies=[Depends(current_superuser)],
    summary="Edit a run's name, mission type or campaign",
    description=(
        "Superuser only (401 without a valid token, 403 for a regular account). Changes the "
        "fields present in the body; at least one is required. `name` is a label of at most "
        "255 characters without control characters, surrounding whitespace is trimmed, `null` "
        "or blank clears it, and it is not unique. `mission_type` is `ground` or `drone` and "
        "cannot be `null`. `campaign_id` is an existing campaign, or `null` to unassign the "
        "run. Unknown fields are rejected with 422, so `id`, `device_id` and `run_id` can never "
        "be changed. The response holds `id`, `device_id`, `run_id`, `name`, `mission_type`, "
        "`campaign_id` and `campaign_name` with the stored values. 404 for an unknown or "
        "trashed run or an unknown campaign."
    ),
)
def update_run(
    changes: RunChanges, run_pk: int = Path(ge=1), db: Session = Depends(get_db)
) -> RunAttributes:
    """Change the fields that are sent; `device_id` and `run_id` can never be changed. A run in
    the trash is not found. Superuser only."""
    if db.scalar(select(Run.id).where(Run.id == run_pk, _NOT_TRASHED)) is None:
        raise _run_not_found()
    _raise_if_campaign_missing(db, changes)

    _apply(db, [run_pk], changes)

    row = db.execute(
        select(Run, Campaign.name)
        .outerjoin(Campaign, Campaign.id == Run.campaign_id)
        .where(Run.id == run_pk)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise _run_not_found()
    run, campaign_name = row
    return RunAttributes(
        id=run.id,
        device_id=run.device_id,
        run_id=run.run_id,
        name=run.name,
        mission_type=run.mission_type,
        campaign_id=run.campaign_id,
        campaign_name=campaign_name,
    )


@router.patch(
    "",
    response_model=RunBulkUpdateResponse,
    dependencies=[Depends(current_superuser)],
    summary="Apply the same changes to several runs",
    description=(
        "Superuser only. Body `{\"ids\": [42, 43], \"changes\": {\"mission_type\": \"drone\", "
        "\"campaign_id\": 3}}`. `changes` takes the same fields as the single update and needs "
        "at least one. `ids` holds 1 to 500 positive integers; duplicates are ignored. The "
        "request is atomic: it runs in one transaction, and if any id (or the campaign) does "
        "not exist, nothing is changed and the response is 404 without naming the offending "
        "id. A run in the trash counts as not existing. Returns `{\"updated\": n}`, the number "
        "of distinct runs changed. 422 for an empty `ids` or `changes`, more than 500 ids, "
        "invalid values or unknown fields."
    ),
)
def update_runs(payload: RunBulkUpdate, db: Session = Depends(get_db)) -> RunBulkUpdateResponse:
    """All-or-nothing: if any id does not exist or is in the trash, nothing is changed and the
    request fails with 404. Superuser only."""
    existing = db.scalar(
        select(func.count()).select_from(Run).where(Run.id.in_(payload.ids), _NOT_TRASHED)
    )
    if existing != len(payload.ids):
        raise _run_not_found()
    _raise_if_campaign_missing(db, payload.changes)

    _apply(db, payload.ids, payload.changes)
    return RunBulkUpdateResponse(updated=len(payload.ids))


@router.get(
    "/trash",
    response_model=TrashedRunListResponse,
    dependencies=[Depends(current_superuser)],
    summary="List the runs in the trash",
    description=(
        "Superuser only. Runs stay in the trash until they are deleted permanently; there is "
        "no automatic purge. Lists them, most recently trashed first, with who moved them "
        "there. Unlike `GET /runs`, runs without measurements are listed too, and their "
        "`start` and `end` are `null`. `deleted_by` and `deleted_by_email` are `null` once "
        "that user has been removed. `page` starts at 1, `page_size` is 1 to 100 (default 25)."
    ),
)
def list_trashed_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
) -> TrashedRunListResponse:
    """Runs in the trash, most recently trashed first, with who moved them there. Superuser
    only."""
    result = query_trashed_runs(db, page, page_size)
    return TrashedRunListResponse(
        runs=result.runs, total=result.total, page=page, page_size=page_size
    )


@router.delete(
    "/{run_pk}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Move a run to the trash",
    description=(
        "Superuser only. Moves the run to the trash. Its measurements and latency results are "
        "kept but hidden from every endpoint: the runs list, campaign periods, the public and "
        "authenticated map, extent, raw and export endpoints. Answers 204 without a body. A "
        "device that uploads into a trashed run is answered as usual; the data is stored on "
        "the trashed run, which stays in the trash until it is restored. 404 for an unknown "
        "run or one that is already in the trash."
    ),
)
def delete_run(
    run_pk: int = Path(ge=1),
    user: User = Depends(current_superuser),
    db: Session = Depends(get_db),
) -> Response:
    """Moves the run with all its measurements and latency results to the trash, where it is
    hidden from every list, map and export until it is restored or deleted permanently. A run
    already in the trash is not found. Superuser only."""
    result = db.execute(
        update(Run)
        .where(Run.id == run_pk, _NOT_TRASHED)
        .values(deleted_at=datetime.now(UTC), deleted_by=user.id)
    )
    if result.rowcount != 1:
        db.rollback()
        raise _run_not_found()
    db.commit()

    logger.info("moved run to trash: user_id=%s run_id=%s", user.id, run_pk)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{run_pk}/restore",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Restore a run from the trash",
    description=(
        "Superuser only. Takes the run out of the trash with all its data, including anything "
        "uploaded while it was there. Its name, mission type and campaign are kept; a campaign "
        "deleted in the meantime leaves it unassigned. Answers 204 without a body. 404 for an "
        "unknown run or one that is not in the trash."
    ),
)
def restore_run(
    run_pk: int = Path(ge=1),
    user: User = Depends(current_superuser),
    db: Session = Depends(get_db),
) -> Response:
    """Makes a trashed run visible again, with every measurement and latency result it has,
    including any uploaded while it was in the trash. 404 unless the run is in the trash.
    Superuser only."""
    result = db.execute(
        update(Run).where(Run.id == run_pk, _TRASHED).values(deleted_at=None, deleted_by=None)
    )
    if result.rowcount != 1:
        db.rollback()
        raise _run_not_found()
    db.commit()

    logger.info("restored run from trash: user_id=%s run_id=%s", user.id, run_pk)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/trash/{run_pk}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete a run from the trash with all its data",
    description=(
        "Superuser only. Deletes a trashed run and all its measurements and latency results; "
        "other runs and devices are untouched. This cannot be undone. Only runs in the trash "
        "can be deleted this way, so removing a run for good always takes two steps. A device "
        "that uploads the same `run_id` afterwards creates a new run with a new `id`: deleting "
        "removes the stored data, not the device's ability to send it again. Answers 204 "
        "without a body; 404 for an unknown run or one that is not in the trash."
    ),
)
def delete_run_permanently(
    run_pk: int = Path(ge=1),
    user: User = Depends(current_superuser),
    db: Session = Depends(get_db),
) -> Response:
    """Irreversibly deletes a run in the trash and, through the foreign keys, every measurement
    and latency result of it. 404 unless the run is in the trash, so an active run can only be
    removed in two steps. A device uploading the same `run_id` later creates a new run.
    Superuser only."""
    run = db.scalar(select(Run).where(Run.id == run_pk, _TRASHED).with_for_update())
    if run is None:
        raise _run_not_found()
    point_count = db.scalar(
        select(func.count()).select_from(Measurement).where(Measurement.run_pk == run_pk)
    )
    latency_result_count = db.scalar(
        select(func.count())
        .select_from(LatencyTestResult)
        .where(LatencyTestResult.run_pk == run_pk)
    )

    device_id = run.device_id
    db.delete(run)
    db.commit()

    logger.info(
        "permanently deleted run: user_id=%s run_id=%s device_id=%s points=%s "
        "latency_results=%s",
        user.id,
        run_pk,
        device_id,
        point_count,
        latency_result_count,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
