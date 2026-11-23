"""Pydantic schemas for the runs API."""

import unicodedata
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator

from app.models.run import RUN_NAME_MAX_LENGTH

MAX_RUNS_PER_BULK_UPDATE = 500


class RunSortKey(StrEnum):
    START = "start"
    DURATION = "duration"
    POINT_COUNT = "point_count"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class MissionType(StrEnum):
    GROUND = "ground"
    DRONE = "drone"


class Run(BaseModel):
    """One drive or flight of one device, aggregated from its measurements."""

    id: int = Field(description="Internal id of the run, used by the edit and delete endpoints")
    name: str | None = Field(description="User-editable label; null until one is set")
    run_id: str = Field(description="Device-supplied run id; immutable, matches uploads to the run")
    device_id: str = Field(description="Device that recorded the run; immutable")
    mission_type: str = Field(description="`ground` or `drone`; editable")
    start: datetime = Field(description="Timestamp of the run's first measurement")
    end: datetime = Field(description="Timestamp of the run's last measurement")
    point_count: int = Field(description="Number of measurements in the run")
    mean_rsrp: float | None = Field(description="Mean RSRP of the non-null values; null if none")
    mean_rsrq: float | None = Field(description="Mean RSRQ of the non-null values; null if none")
    mean_sinr: float | None = Field(description="Mean SINR of the non-null values; null if none")
    campaign_id: int | None = Field(description="Campaign the run is assigned to, if any")
    campaign_name: str | None = Field(description="Name of that campaign; null with `campaign_id`")
    legacy: bool = Field(description="True for synthetic runs (`run_id` starts with `legacy-`)")


class RunListResponse(BaseModel):
    runs: list[Run]
    total: int = Field(description="Number of runs matching the filters, across all pages")
    page: int = Field(description="Page number, from 1")
    page_size: int = Field(description="Runs per page")


class RunChanges(BaseModel):
    """The editable attributes of a run; only the fields that are sent are changed. `device_id`,
    `run_id` and `id` are deliberately absent and, with every other unknown field, rejected."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        max_length=RUN_NAME_MAX_LENGTH,
        description="Label shown for the run; null or blank clears it",
    )
    mission_type: MissionType | None = Field(default=None, description="Cannot be null")
    campaign_id: int | None = Field(
        default=None, description="Existing campaign, or null to unassign the run"
    )

    @field_validator("name")
    @classmethod
    def clean_name(cls, name: str | None) -> str | None:
        if name is None:
            return None
        if any(unicodedata.category(char) in ("Cc", "Cf", "Zl", "Zp") for char in name):
            raise ValueError("name must not contain control characters")
        return name.strip() or None

    @model_validator(mode="after")
    def check_changes(self) -> "RunChanges":
        if not self.model_fields_set:
            raise ValueError("at least one field to change is required")
        if "mission_type" in self.model_fields_set and self.mission_type is None:
            raise ValueError("mission_type cannot be null")
        return self

    def as_values(self) -> dict:
        """Column values for exactly the fields that were sent."""
        return {field: getattr(self, field) for field in self.model_fields_set}


class RunBulkUpdate(BaseModel):
    """Apply the same changes to several runs at once, all or nothing."""

    model_config = ConfigDict(extra="forbid")

    ids: list[PositiveInt] = Field(min_length=1, max_length=MAX_RUNS_PER_BULK_UPDATE)
    changes: RunChanges

    @field_validator("ids")
    @classmethod
    def deduplicate(cls, ids: list[int]) -> list[int]:
        return list(dict.fromkeys(ids))


class RunAttributes(BaseModel):
    """A run's own attributes, as returned after editing it."""

    id: int = Field(description="Internal id of the run")
    device_id: str = Field(description="Device that recorded the run")
    run_id: str = Field(description="Device-supplied run id")
    name: str | None = Field(description="Label of the run; null if none")
    mission_type: str = Field(description="`ground` or `drone`")
    campaign_id: int | None = Field(description="Campaign the run is assigned to, if any")
    campaign_name: str | None = Field(description="Name of that campaign; null with `campaign_id`")


class RunBulkUpdateResponse(BaseModel):
    updated: int = Field(description="Number of distinct runs changed")


class TrashedRun(BaseModel):
    """A run in the trash, as listed for superusers."""

    id: int = Field(description="Internal id of the run, used by the restore and delete endpoints")
    name: str | None = Field(description="Label of the run; null if none")
    run_id: str = Field(description="Device-supplied run id")
    device_id: str = Field(description="Device that recorded the run")
    mission_type: str = Field(description="`ground` or `drone`")
    start: datetime | None = Field(description="First measurement; null for a run without any")
    end: datetime | None = Field(description="Last measurement; null for a run without any")
    point_count: int = Field(description="Number of measurements in the run")
    latency_result_count: int = Field(description="Number of latency results in the run")
    campaign_id: int | None = Field(description="Campaign the run is assigned to, if any")
    campaign_name: str | None = Field(description="Name of that campaign; null with `campaign_id`")
    legacy: bool = Field(description="True for synthetic runs (`run_id` starts with `legacy-`)")
    deleted_at: datetime = Field(description="When the run was moved to the trash")
    deleted_by: int | None = Field(
        description="Id of the user who moved the run to the trash; null once that user is gone"
    )
    deleted_by_email: str | None = Field(description="Login of that user, null with `deleted_by`")


class TrashedRunListResponse(BaseModel):
    runs: list[TrashedRun]
    total: int = Field(description="Number of runs in the trash, across all pages")
    page: int = Field(description="Page number, from 1")
    page_size: int = Field(description="Runs per page")
