"""Run identity: one run is one drive/flight of one device.

Devices supply a `run_id` with their uploads. Rows without one (older firmware, or data stored
before runs existed) get a synthetic legacy id instead, derived deterministically from the row
itself so the ingest fallback and the migration backfill always agree.
"""

from datetime import UTC, datetime

LEGACY_RUN_ID_PREFIX = "legacy-"

# 'legacy-' + device_id (255) + '-' + mission_type (255) + '-' + 'YYYY-MM-DD'
RUN_ID_COLUMN_LENGTH = 600


def legacy_run_id(device_id: str, mission_type: str, timestamp: datetime) -> str:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    day = timestamp.astimezone(UTC).date().isoformat()
    return f"{LEGACY_RUN_ID_PREFIX}{device_id}-{mission_type}-{day}"


def is_legacy_run_id(run_id: str) -> bool:
    return run_id.startswith(LEGACY_RUN_ID_PREFIX)
