"""Unit tests for app/schemas/campaign.py: name validation and run reference lists.

Pure Pydantic-level tests - no DB, no app, no auth needed.
"""
import pytest
from pydantic import ValidationError

from app.schemas.campaign import (
    MAX_RUNS_PER_REQUEST,
    CampaignCreate,
    CampaignUpdate,
    RunAssignment,
)


def test_campaign_create_accepts_valid_slug_name():
    campaign = CampaignCreate(name="summer-2026")

    assert campaign.name == "summer-2026"


@pytest.mark.parametrize(
    "name",
    ["Summer2026", "summer_2026", "summer 2026", "-summer", "summer-", "sum--mer", ""],
)
def test_campaign_create_rejects_invalid_names(name):
    with pytest.raises(ValidationError):
        CampaignCreate(name=name)


def test_campaign_create_rejects_name_over_max_length():
    with pytest.raises(ValidationError):
        CampaignCreate(name="a" * 64)


def test_campaign_create_no_longer_takes_a_date_range():
    campaign = CampaignCreate.model_validate(
        {"name": "summer-2026", "start_date": "2026-06-01", "end_date": "2026-08-31"}
    )

    assert not hasattr(campaign, "start_date")
    assert not hasattr(campaign, "end_date")


def test_campaign_update_allows_all_fields_omitted():
    update = CampaignUpdate()

    assert update.name is None


def test_campaign_update_rejects_invalid_name():
    with pytest.raises(ValidationError):
        CampaignUpdate(name="Invalid Name")


def test_run_assignment_deduplicates_run_references_keeping_order():
    assignment = RunAssignment.model_validate(
        {
            "runs": [
                {"device_id": "dev-1", "run_id": "run-b"},
                {"device_id": "dev-1", "run_id": "run-a"},
                {"device_id": "dev-1", "run_id": "run-b"},
                {"device_id": "dev-2", "run_id": "run-b"},
            ]
        }
    )

    assert [(r.device_id, r.run_id) for r in assignment.runs] == [
        ("dev-1", "run-b"),
        ("dev-1", "run-a"),
        ("dev-2", "run-b"),
    ]


def test_run_assignment_rejects_an_empty_list():
    with pytest.raises(ValidationError):
        RunAssignment(runs=[])


def test_run_assignment_rejects_more_runs_than_the_request_limit():
    runs = [{"device_id": "dev-1", "run_id": f"run-{i}"} for i in range(MAX_RUNS_PER_REQUEST + 1)]

    with pytest.raises(ValidationError):
        RunAssignment.model_validate({"runs": runs})


@pytest.mark.parametrize("field", ["device_id", "run_id"])
def test_run_assignment_rejects_empty_or_oversized_identifiers(field):
    valid = {"device_id": "dev-1", "run_id": "run-1"}
    for bad in ("", "x" * 601):
        with pytest.raises(ValidationError):
            RunAssignment.model_validate({"runs": [{**valid, field: bad}]})
