"""Superuser campaign management API.

Manages the named campaigns that the public map's heatmap/export endpoints aggregate within (see
app/measurements_query.py) and which runs belong to them. A campaign is defined by its assigned
runs; its period is derived from them (see app/campaigns_query.py). Mirrors app/routers/admin.py's
router-level `dependencies=[Depends(current_superuser)]` pattern.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, select, tuple_, update
from sqlalchemy.orm import Session

from app.auth import current_superuser
from app.campaigns_query import get_campaign, list_campaigns
from app.db import get_db
from app.models.campaign import Campaign as CampaignModel
from app.models.run import Run
from app.schemas.campaign import (
    Campaign,
    CampaignCreate,
    CampaignListResponse,
    CampaignUpdate,
    RunAssignment,
)

router = APIRouter(
    prefix="/admin/campaigns", tags=["admin"], dependencies=[Depends(current_superuser)]
)


def _get_campaign_or_404(db: Session, campaign_id: int) -> CampaignModel:
    campaign = db.get(CampaignModel, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return campaign


def _raise_if_name_taken(db: Session, name: str) -> None:
    if db.scalar(select(CampaignModel.id).where(CampaignModel.name == name)) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A campaign with this name already exists.",
        )


def _campaign_response(db: Session, campaign_id: int) -> Campaign:
    campaign = get_campaign(db, campaign_id)
    assert campaign is not None
    return campaign


def _run_keys(assignment: RunAssignment):
    """The referenced runs, leaving out those in the trash."""
    return and_(
        tuple_(Run.device_id, Run.run_id).in_(
            [(run.device_id, run.run_id) for run in assignment.runs]
        ),
        Run.deleted_at.is_(None),
    )


def _raise_unless_all_found(db: Session, assignment: RunAssignment, *conditions) -> None:
    """404 unless every referenced run exists, is not in the trash (and satisfies `conditions`).
    The detail never echoes which reference was the problem."""
    found = db.scalar(
        select(func.count())
        .select_from(Run)
        .where(_run_keys(assignment), *conditions)
    )
    if found != len(assignment.runs):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")


@router.get(
    "",
    response_model=CampaignListResponse,
    summary="List campaigns",
    description=(
        "Superuser only. All campaigns, oldest period first and campaigns without runs last. "
        "A campaign is a named group of runs; a run belongs to at most one campaign. The period "
        "is derived, not entered: `start` is the UTC day of the earliest and `end` the UTC day "
        "of the latest measurement over the campaign's runs, both `null` while it has no runs. "
        "Runs in the trash do not count. The public campaign picker uses "
        "`GET /measurements/campaigns`."
    ),
)
def list_all_campaigns(db: Session = Depends(get_db)) -> CampaignListResponse:
    """List all campaigns with their derived period, oldest first. Superuser only."""
    return CampaignListResponse(campaigns=list_campaigns(db))


@router.post(
    "",
    response_model=Campaign,
    status_code=status.HTTP_201_CREATED,
    summary="Create a campaign",
    description=(
        "Superuser only. Creates an empty campaign from `{\"name\": ...}`; runs are assigned "
        "afterwards. The name is a slug (lowercase alphanumeric segments separated by single "
        "hyphens, at most 63 characters) because it is shown in the public campaign listing. "
        "400 if the name is taken, 422 if it is invalid."
    ),
)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)) -> Campaign:
    """Create an empty campaign. Superuser only."""
    _raise_if_name_taken(db, payload.name)

    campaign = CampaignModel(name=payload.name)
    db.add(campaign)
    db.commit()
    return _campaign_response(db, campaign.id)


@router.patch(
    "/{campaign_id}",
    response_model=Campaign,
    summary="Rename a campaign",
    description=(
        "Superuser only. Renames the campaign with `{\"name\": ...}`, which follows the same slug "
        "rules as on creation. 404 for an unknown campaign, 400 if the name is taken, 422 if it "
        "is invalid."
    ),
)
def update_campaign(
    campaign_id: int, payload: CampaignUpdate, db: Session = Depends(get_db)
) -> Campaign:
    """Partially update a campaign. Superuser only."""
    campaign = _get_campaign_or_404(db, campaign_id)

    if payload.name is not None and payload.name != campaign.name:
        _raise_if_name_taken(db, payload.name)
        campaign.name = payload.name
        db.commit()
    return _campaign_response(db, campaign_id)


@router.delete(
    "/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a campaign",
    description=(
        "Superuser only. Deletes the campaign; its runs are kept and become unassigned. 404 for "
        "an unknown campaign."
    ),
)
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a campaign; its runs become unassigned. Superuser only."""
    campaign = _get_campaign_or_404(db, campaign_id)
    db.delete(campaign)
    db.commit()


@router.post(
    "/{campaign_id}/runs",
    response_model=Campaign,
    summary="Assign runs to a campaign",
    description=(
        "Superuser only. Assigns the runs of `{\"runs\": [{\"device_id\", \"run_id\"}, ...]}` to "
        "the campaign and moves them out of any other campaign. The list holds 1 to 500 "
        "entries and is deduplicated. All-or-nothing in one transaction: if any referenced run "
        "does not exist or is in the trash the response is `404 {\"detail\": \"Run not found\"}` "
        "without saying which reference, and nothing changes. Runs exist once a device has "
        "uploaded measurements for them; `GET /runs?unassigned=true` lists the candidates. "
        "Returns the updated campaign."
    ),
)
def assign_runs(
    campaign_id: int, payload: RunAssignment, db: Session = Depends(get_db)
) -> Campaign:
    """Assign runs to the campaign, moving them out of any other campaign. All-or-nothing: 404 if
    any run does not exist or is in the trash. Superuser only."""
    _get_campaign_or_404(db, campaign_id)
    _raise_unless_all_found(db, payload)

    db.execute(update(Run).where(_run_keys(payload)).values(campaign_id=campaign_id))
    db.commit()
    return _campaign_response(db, campaign_id)


@router.post(
    "/{campaign_id}/runs/unassign",
    response_model=Campaign,
    summary="Remove runs from a campaign",
    description=(
        "Superuser only. Takes the same body as assigning: 1 to 500 deduplicated run "
        "references. All-or-nothing: if any referenced run does not exist, is in the trash or "
        "is not in this campaign, the response is `404 {\"detail\": \"Run not found\"}` without "
        "saying which reference, and nothing changes. Returns the updated campaign."
    ),
)
def unassign_runs(
    campaign_id: int, payload: RunAssignment, db: Session = Depends(get_db)
) -> Campaign:
    """Remove runs from the campaign. All-or-nothing: 404 if any run does not exist or is not
    assigned to this campaign, or is in the trash. Superuser only."""
    _get_campaign_or_404(db, campaign_id)
    _raise_unless_all_found(db, payload, Run.campaign_id == campaign_id)

    db.execute(update(Run).where(_run_keys(payload)).values(campaign_id=None))
    db.commit()
    return _campaign_response(db, campaign_id)
