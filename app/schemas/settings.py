"""Pydantic schemas for the superuser-only application settings API."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt

# Well below the Postgres/Python int limits; a cap this large is effectively "unlimited" anyway.
MAX_RAW_ROW_CAP = 2_147_483_647

RawRowCap = Annotated[StrictInt, Field(ge=1, le=MAX_RAW_ROW_CAP)]


class RawRowCapUpdate(BaseModel):
    """`value` is required: `null` explicitly means unlimited, omitting it is an error."""

    model_config = ConfigDict(extra="forbid")

    value: RawRowCap | None = Field(
        description="Max rows a logged-in user's raw query may return; null for unlimited"
    )


class RawRowCapSetting(BaseModel):
    value: int | None = Field(
        description="Row cap of logged-in users' raw queries; null means unlimited"
    )
    updated_at: datetime | None = Field(description="Null while the default has never been changed")
    updated_by: int | None = Field(description="User id of the last editor, if still existing")


MIN_SHUTDOWN_CONFIRM_INTERVALS = 1
MAX_SHUTDOWN_CONFIRM_INTERVALS = 20
MIN_SHUTDOWN_CONFIRM_SECONDS = 10
MAX_SHUTDOWN_CONFIRM_SECONDS = 3600

ShutdownConfirmIntervals = Annotated[
    StrictInt, Field(ge=MIN_SHUTDOWN_CONFIRM_INTERVALS, le=MAX_SHUTDOWN_CONFIRM_INTERVALS)
]
ShutdownConfirmSeconds = Annotated[
    StrictInt | StrictFloat,
    Field(ge=MIN_SHUTDOWN_CONFIRM_SECONDS, le=MAX_SHUTDOWN_CONFIRM_SECONDS, allow_inf_nan=False),
]


class ShutdownConfirmation(BaseModel):
    """How long a device must stay silent after a shutdown-now's `received` ack for the shutdown
    to count as successful: `intervals` heartbeat intervals or a fixed `seconds`
    span, whichever `mode` selects. The unused field keeps its value so switching modes does not
    lose it."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["intervals", "seconds"] = Field(
        default="intervals", description="Which of `intervals` and `seconds` applies"
    )
    intervals: ShutdownConfirmIntervals = Field(
        default=4, description="Silence required, in heartbeat intervals (1 to 20)"
    )
    seconds: ShutdownConfirmSeconds = Field(
        default=60, description="Silence required, in seconds (10 to 3600)"
    )


class ShutdownConfirmationSetting(ShutdownConfirmation):
    updated_at: datetime | None = Field(description="Null while the default has never been changed")
    updated_by: int | None = Field(description="User id of the last editor, if still existing")
