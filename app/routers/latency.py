"""Router for latency test result upload endpoint."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.device_auth import verify_device_auth
from app.models import Device
from app.models.latency import LatencyTestResult
from app.run_ids import legacy_run_id
from app.runs_store import upsert_runs
from app.schemas.latency import LatencyResult, LatencyResultArray

router = APIRouter(tags=["latency"])


def _parse_timestamp(value: str) -> datetime:
    """Parse a device-supplied ISO 8601 timestamp, accepting a trailing 'Z' for UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _run_id(result: LatencyResult) -> str:
    return result.run_id or legacy_run_id(
        result.device_id, result.mission_type, _parse_timestamp(result.start_timestamp)
    )


def _build_row(result: LatencyResult, run_pk: int) -> LatencyTestResult:
    return LatencyTestResult(
        device_id=result.device_id,
        test_type=result.test_type.value,
        flent_test=result.flent_test,
        run_pk=run_pk,
        start_timestamp=_parse_timestamp(result.start_timestamp),
        end_timestamp=_parse_timestamp(result.end_timestamp),
        start_fix=result.start_fix.model_dump(mode="json"),
        end_fix=result.end_fix.model_dump(mode="json"),
        baseline_rtt_ms=result.baseline_rtt_ms,
        rtt_under_load_ms=result.rtt_under_load_ms,
        rtt_p99_ms=result.rtt_p99_ms,
        download_mbits_s=result.download_mbits_s,
        upload_mbits_s=result.upload_mbits_s,
        idempotency_key=result.idempotency_key,
    )


def _insert_results(db: Session, results: list[LatencyResult]) -> None:
    """Insert the results attached to their runs (created on first sight) in one transaction."""
    result_runs = [(result, _run_id(result)) for result in results]
    run_pks = upsert_runs(
        db, ((result.device_id, run_id, result.mission_type) for result, run_id in result_runs)
    )
    db.add_all(
        _build_row(result, run_pks[(result.device_id, run_id)]) for result, run_id in result_runs
    )
    db.commit()


@router.post(
    "/latency-results",
    status_code=status.HTTP_201_CREATED,
    summary="Upload latency test results (device)",
    description=(
        "Device endpoint: ingests one latency test result (a baseline or under-load run), or "
        "a JSON array of several, from a registered device. The device authenticates with its "
        "`X-Device-ID` and `X-Device-Key` headers, which are checked before the body is read, "
        "and every result's `device_id` must be the authenticated device's (403 otherwise). "
        "Each result's `run_id` assigns it to a run, which is created on first sight; results "
        "without one belong to a synthetic `legacy-<device_id>-<mission_type>-<YYYY-MM-DD>` "
        "run. The upload is idempotent: a result whose `idempotency_key` already exists for the "
        "device, including one earlier in the same array, is skipped instead of stored again or "
        "rejected, so a retry after a lost response creates no duplicate. `count` in the "
        "response (`{\"status\": \"success\", \"count\", \"device_id\"}`) counts every item "
        "accepted, skipped duplicates included. 201 on success, 401 for missing or wrong device "
        "credentials, 422 for an invalid body."
    ),
)
async def upload_latency_result(
    payload: LatencyResult | LatencyResultArray,
    device: Device = Depends(verify_device_auth),
    db: Session = Depends(get_db),
) -> dict:
    """Receive and store one or more latency test results from a device.

    Authenticated via X-Device-Key header with per-device lookup, same as
    `POST /api/measurements`. Auth is a FastAPI dependency, so it runs before the request
    body is parsed. Accepts either a single `LatencyResult` object (the original shape) or a
    JSON array of them, mirroring `upload_measurements`'s `DatapointArray` batch support -
    every item's `device_id` is checked against the authenticated device before anything is
    inserted, same as that endpoint does for each datapoint.

    Idempotency: a result whose `idempotency_key` already exists for this device (including
    one submitted earlier in the same array) is skipped rather than inserted again or
    rejected, so a device retrying after a lost response doesn't create a duplicate row.
    `count` in the response reflects every item accepted, deduped or not - from the device's
    perspective, all of them are now safely recorded.
    """
    results = payload.root if isinstance(payload, LatencyResultArray) else [payload]

    for result in results:
        if result.device_id != device.device_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Payload device_id {result.device_id} does not match "
                    f"authenticated device {device.device_id}"
                ),
            )

    requested_keys = {r.idempotency_key for r in results if r.idempotency_key is not None}
    existing_keys: set[str] = set()
    if requested_keys:
        existing_keys = set(
            db.scalars(
                select(LatencyTestResult.idempotency_key).where(
                    LatencyTestResult.device_id == device.device_id,
                    LatencyTestResult.idempotency_key.in_(requested_keys),
                )
            )
        )

    seen_keys: set[str] = set()
    new_results = []
    for result in results:
        key = result.idempotency_key
        if key is not None:
            if key in existing_keys or key in seen_keys:
                continue
            seen_keys.add(key)
        new_results.append(result)

    try:
        _insert_results(db, new_results)
    except IntegrityError:
        # Rare race: a concurrent request for this device inserted one of these idempotency
        # keys after our lookup above but before this commit. Fall back to inserting one row
        # per transaction so the keys that lost the race are skipped instead of failing the
        # whole batch.
        db.rollback()
        for result in new_results:
            try:
                _insert_results(db, [result])
            except IntegrityError:
                db.rollback()

    return {
        "status": "success",
        "count": len(results),
        "device_id": device.device_id,
    }
