"""Write side of runs: matching uploads to their run row."""

from collections.abc import Iterable

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.run import Run

RunKey = tuple[str, str]


def upsert_runs(db: Session, runs: Iterable[tuple[str, str, str]]) -> dict[RunKey, int]:
    """Ids of the runs for the given (device_id, run_id, mission_type) triples, creating any that
    do not exist yet. A run that already exists keeps its stored mission type, name and campaign,
    so edits are never overwritten by a later upload; for a run new in this call the first
    mission type given for it wins.

    The no-op `DO UPDATE` (rather than `DO NOTHING`) makes the statement return the id of
    existing rows too and row-locks them until the transaction ends, so a concurrent delete of
    the run waits for the upload to commit instead of orphaning the rows about to be inserted.
    Keys are sorted so that concurrent uploads lock rows in the same order.
    """
    mission_type_by_key: dict[RunKey, str] = {}
    for device_id, run_id, mission_type in runs:
        mission_type_by_key.setdefault((device_id, run_id), mission_type)
    if not mission_type_by_key:
        return {}

    statement = insert(Run).values(
        [
            {"device_id": device_id, "run_id": run_id, "mission_type": mission_type}
            for (device_id, run_id), mission_type in sorted(mission_type_by_key.items())
        ]
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Run.device_id, Run.run_id], set_={"run_id": statement.excluded.run_id}
    ).returning(Run.id, Run.device_id, Run.run_id)
    return {(row.device_id, row.run_id): row.id for row in db.execute(statement)}
