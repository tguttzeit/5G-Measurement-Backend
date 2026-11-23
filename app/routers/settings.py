"""Superuser-only application settings API.

Clients never need to read the raw row cap: it is enforced server-side in the authenticated
raw queries (see `app.app_settings`), so these endpoints exist only for the Settings page.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.app_settings import (
    read_authenticated_raw_row_cap,
    read_shutdown_confirmation,
    set_authenticated_raw_row_cap,
    set_shutdown_confirmation,
)
from app.auth import current_superuser
from app.db import get_db
from app.models.user import User
from app.routers.field_only_validation import FieldOnlyValidationErrorRoute
from app.schemas.settings import (
    RawRowCapSetting,
    RawRowCapUpdate,
    ShutdownConfirmation,
    ShutdownConfirmationSetting,
)

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(current_superuser)],
    route_class=FieldOnlyValidationErrorRoute,
)


def _raw_row_cap_response(db: Session) -> RawRowCapSetting:
    stored = read_authenticated_raw_row_cap(db)
    return RawRowCapSetting(
        value=stored.value, updated_at=stored.updated_at, updated_by=stored.updated_by
    )


@router.get(
    "/raw-row-cap",
    response_model=RawRowCapSetting,
    summary="Get the row cap of logged-in users' raw map queries",
    description=(
        "Superuser only (401 without a valid token, 403 for a non-superuser). Returns "
        "`{\"value\", \"updated_at\", \"updated_by\"}`. `value` is the maximum number of rows a "
        "logged-in user's raw map query (`GET /measurements/detailed` with `view=raw`, "
        "`GET /latency-results/raw`) may return; `null` means unlimited, which is the default. "
        "The cap is enforced server-side, so clients never need to read it. Guests are not "
        "affected: the public point endpoints keep a fixed cap of 5000 rows."
    ),
)
def get_raw_row_cap(db: Session = Depends(get_db)) -> RawRowCapSetting:
    """The row cap on logged-in users' raw map queries; `value: null` means unlimited (the
    default). Guests are not affected - they always keep the fixed public cap. Superuser only."""
    return _raw_row_cap_response(db)


@router.put(
    "/raw-row-cap",
    response_model=RawRowCapSetting,
    summary="Set the row cap of logged-in users' raw map queries",
    description=(
        "Superuser only. Body `{\"value\": int | null}`. `value` is required; `null` means "
        "unlimited, otherwise it is an integer from 1 to 2147483647 (booleans, floats and "
        "strings are rejected). With a cap set, a raw query matching more rows is answered "
        "with 400 instead of a truncated result. Returns the new setting in the same shape as "
        "the read endpoint. An invalid body is a 422 that names the field and the violated "
        "constraint but does not echo the submitted value."
    ),
)
def put_raw_row_cap(
    payload: RawRowCapUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_superuser),
) -> RawRowCapSetting:
    """Set the row cap on logged-in users' raw map queries (`null` for unlimited). Superuser
    only."""
    set_authenticated_raw_row_cap(db, payload.value, user.id)
    return _raw_row_cap_response(db)


def _shutdown_confirmation_response(db: Session) -> ShutdownConfirmationSetting:
    stored = read_shutdown_confirmation(db)
    return ShutdownConfirmationSetting(
        **stored.value.model_dump(), updated_at=stored.updated_at, updated_by=stored.updated_by
    )


@router.get(
    "/shutdown-confirmation",
    response_model=ShutdownConfirmationSetting,
    summary="Get the shutdown confirmation rule",
    description=(
        "Superuser only. How long a device must stay silent after the acknowledgement of a "
        "`shutdown-now` command before the shutdown counts as successful: `mode` is "
        "`intervals` (`intervals` heartbeat intervals) or `seconds` (a fixed `seconds` span). "
        "Defaults to `{\"mode\": \"intervals\", \"intervals\": 4, \"seconds\": 60}`. The "
        "response also carries `updated_at` and `updated_by`."
    ),
)
def get_shutdown_confirmation(db: Session = Depends(get_db)) -> ShutdownConfirmationSetting:
    """How long a device must stay silent after a shutdown-now's ack for the shutdown to count
    as successful: `intervals` heartbeat intervals or a fixed `seconds` span, per `mode`.
    Defaults to 4 intervals. Superuser only."""
    return _shutdown_confirmation_response(db)


@router.put(
    "/shutdown-confirmation",
    response_model=ShutdownConfirmationSetting,
    summary="Set the shutdown confirmation rule",
    description=(
        "Superuser only. Body `{\"mode\", \"intervals\", \"seconds\"}`, all optional with the "
        "defaults of the read endpoint. `mode` selects which of the two thresholds applies; "
        "the other keeps its value so switching modes loses nothing. `intervals` is an "
        "integer from 1 to 20, `seconds` a number from 10 to 3600 (booleans, strings, NaN and "
        "infinity are rejected). Returns the new setting. An invalid body is a 422 that names "
        "the field and the violated constraint but does not echo the submitted value."
    ),
)
def put_shutdown_confirmation(
    payload: ShutdownConfirmation,
    db: Session = Depends(get_db),
    user: User = Depends(current_superuser),
) -> ShutdownConfirmationSetting:
    """Set the shutdown-success threshold. Superuser only."""
    set_shutdown_confirmation(db, payload, user.id)
    return _shutdown_confirmation_response(db)
