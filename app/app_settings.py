"""Typed accessors for the persisted application settings (`app_settings` table).

Each setting has a built-in default that applies when its row is missing or its stored value no
longer validates, so a corrupted row degrades to the default instead of failing requests.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting
from app.schemas.settings import RawRowCap, ShutdownConfirmation

logger = logging.getLogger(__name__)

AUTHENTICATED_RAW_ROW_CAP_KEY = "authenticated_raw_row_cap"

SHUTDOWN_CONFIRMATION_KEY = "shutdown_confirmation"

_raw_row_cap_adapter = TypeAdapter(RawRowCap | None)


@dataclass(frozen=True)
class StoredRawRowCap:
    value: int | None
    updated_at: datetime | None
    updated_by: int | None


def read_authenticated_raw_row_cap(db: Session) -> StoredRawRowCap:
    """The row cap for logged-in users' raw queries plus who last changed it; `None` is
    unlimited, which is also the default when nothing was ever stored."""
    row = db.get(AppSetting, AUTHENTICATED_RAW_ROW_CAP_KEY)
    if row is None:
        return StoredRawRowCap(value=None, updated_at=None, updated_by=None)

    try:
        value = _raw_row_cap_adapter.validate_python(row.value, strict=True)
    except ValidationError:
        logger.warning("Stored %s is invalid; using the default", AUTHENTICATED_RAW_ROW_CAP_KEY)
        value = None
    return StoredRawRowCap(value=value, updated_at=row.updated_at, updated_by=row.updated_by)


def get_authenticated_raw_row_cap(db: Session) -> int | None:
    return read_authenticated_raw_row_cap(db).value


def set_authenticated_raw_row_cap(db: Session, value: int | None, updated_by: int | None) -> None:
    row = db.get(AppSetting, AUTHENTICATED_RAW_ROW_CAP_KEY)
    if row is None:
        row = AppSetting(key=AUTHENTICATED_RAW_ROW_CAP_KEY)
        db.add(row)
    row.value = value
    row.updated_by = updated_by
    db.commit()


@dataclass(frozen=True)
class StoredShutdownConfirmation:
    value: ShutdownConfirmation
    updated_at: datetime | None
    updated_by: int | None


def read_shutdown_confirmation(db: Session) -> StoredShutdownConfirmation:
    """The shutdown-success threshold plus who last changed it; the default (4 heartbeat
    intervals) applies when nothing was stored or the stored value no longer validates."""
    row = db.get(AppSetting, SHUTDOWN_CONFIRMATION_KEY)
    if row is None:
        return StoredShutdownConfirmation(ShutdownConfirmation(), None, None)

    try:
        value = ShutdownConfirmation.model_validate(row.value, strict=True)
    except ValidationError:
        logger.warning("Stored %s is invalid; using the default", SHUTDOWN_CONFIRMATION_KEY)
        value = ShutdownConfirmation()
    return StoredShutdownConfirmation(value, row.updated_at, row.updated_by)


def get_shutdown_confirmation(db: Session) -> ShutdownConfirmation:
    return read_shutdown_confirmation(db).value


def set_shutdown_confirmation(
    db: Session, value: ShutdownConfirmation, updated_by: int | None
) -> None:
    row = db.get(AppSetting, SHUTDOWN_CONFIRMATION_KEY)
    if row is None:
        row = AppSetting(key=SHUTDOWN_CONFIRMATION_KEY)
        db.add(row)
    row.value = value.model_dump(mode="json")
    row.updated_by = updated_by
    db.commit()
