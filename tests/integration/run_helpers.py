"""Test-data helper for rows that belong to a run.

`run_row` builds a `Measurement` or `LatencyTestResult` from the run attributes the tests care
about (device, device-supplied run id, mission type). Just before the session flushes, the row is
attached to its run, which is created if it does not exist yet - the same get-or-create the upload
endpoints do. Without an explicit `run_id` the row gets the synthetic legacy run id of its device,
mission type and day, like an upload without one.
"""

from typing import TypeVar

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from app.run_ids import legacy_run_id
from app.runs_store import upsert_runs

_PENDING_RUN = "_pending_run"


Row = TypeVar("Row", Measurement, LatencyTestResult)


def run_row(
    model: type[Row], *, mission_type: str = "ground", run_id: str | None = None, **columns
) -> Row:
    row = model(**columns)
    setattr(row, _PENDING_RUN, (run_id, mission_type))
    return row


def assign_run_id(row: Measurement | LatencyTestResult, run_id: str) -> None:
    """Point a row built by `run_row` at the device-supplied run `run_id` instead."""
    _, mission_type = getattr(row, _PENDING_RUN)
    setattr(row, _PENDING_RUN, (run_id, mission_type))


@event.listens_for(Session, "before_flush")
def _attach_pending_rows_to_their_runs(session: Session, flush_context, instances) -> None:
    for row in list(session.new):
        pending = getattr(row, _PENDING_RUN, None)
        if pending is None or row.run_pk is not None:
            continue
        run_id, mission_type = pending
        timestamp = row.timestamp if isinstance(row, Measurement) else row.start_timestamp
        run_id = run_id or legacy_run_id(row.device_id, mission_type, timestamp)
        row.run_pk = upsert_runs(session, [(row.device_id, run_id, mission_type)])[
            (row.device_id, run_id)
        ]
