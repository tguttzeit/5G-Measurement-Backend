"""Pydantic schemas for campaign management (superuser) and the public campaign listing.

`Campaign` is used for both: it carries only id, name and the period derived from the campaign's
runs, which are all safe to publish. The period is whole UTC days, not timestamps - public
responses never carry the time of individual measurements. Run identifiers and run counts
deliberately never appear here - they stay behind the authenticated runs API.
"""

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Slug-safe: lowercase alphanumeric segments separated by single hyphens, e.g. "summer-2026".
# Keeps `name` safe to echo back through the public, unauthenticated campaign-listing endpoint.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_MAX_LENGTH = 63

# Upper bound for one assign/unassign request, so a superuser cannot make it build an unbounded
# query; larger selections are sent in several requests.
MAX_RUNS_PER_REQUEST = 500


def _validate_name(name: str) -> str:
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "name must be lowercase alphanumeric segments separated by single hyphens "
            "(e.g. 'summer-2026')"
        )
    return name


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return _validate_name(name)


class CampaignUpdate(BaseModel):
    """Partial update: only provided fields are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str | None) -> str | None:
        return _validate_name(name) if name is not None else None


class Campaign(BaseModel):
    id: int
    name: str
    start: date | None = Field(
        description="UTC day of the first measurement of the campaign's oldest run; "
        "null while the campaign has no runs"
    )
    end: date | None = Field(
        description="UTC day of the last measurement of the campaign's newest run; "
        "null while the campaign has no runs"
    )


class CampaignListResponse(BaseModel):
    campaigns: list[Campaign]


class RunReference(BaseModel):
    """Identifies a run the way the runs list does: the device-supplied (device_id, run_id)."""

    model_config = ConfigDict(frozen=True)

    device_id: str = Field(min_length=1, max_length=255)
    run_id: str = Field(min_length=1, max_length=600)


class RunAssignment(BaseModel):
    """The runs to add to (or remove from) a campaign."""

    runs: list[RunReference] = Field(min_length=1, max_length=MAX_RUNS_PER_REQUEST)

    @field_validator("runs")
    @classmethod
    def deduplicate(cls, runs: list[RunReference]) -> list[RunReference]:
        return list(dict.fromkeys(runs))
