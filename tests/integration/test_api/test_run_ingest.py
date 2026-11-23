"""Integration tests for `run_id` handling on the device upload endpoints.

A device-supplied `run_id` is stored as sent; an upload without one gets the synthetic legacy id
(app.run_ids.legacy_run_id) - the same id the migration backfill assigns to pre-existing rows.
"""
import hashlib
import secrets

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device
from app.models.campaign import Campaign
from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from app.models.run import Run

DEVICE_ID = "run-ingest-device-01"
DEVICE_KEY = "correct-horse-battery-staple"
DEVICE_HEADERS = {"X-Device-ID": DEVICE_ID, "X-Device-Key": DEVICE_KEY}

FIX = {"position": {"latitude": 52.5, "longitude": 13.4}, "num_satellites": 8, "placeholder": False}


def _datapoint(**overrides) -> dict:
    return {
        "timestamp": "2026-07-30T23:30:00Z",
        "device_id": DEVICE_ID,
        "mission_type": "ground",
        "fix": FIX,
        "cell_sample": {"rat": "LTE", "rsrp": -95.0, "rsrq": -10.0, "sinr": 12.0},
        **overrides,
    }


def _latency_result(**overrides) -> dict:
    return {
        "test_type": "baseline",
        "flent_test": "ping",
        "device_id": DEVICE_ID,
        "mission_type": "ground",
        "start_timestamp": "2026-07-30T23:30:00Z",
        "end_timestamp": "2026-07-30T23:31:00Z",
        "start_fix": FIX,
        "end_fix": FIX,
        "baseline_rtt_ms": 12.0,
        **overrides,
    }


def _register_device(db_session: Session) -> None:
    db_session.add(
        Device(
            device_id=DEVICE_ID,
            api_key_hash=hashlib.sha256(DEVICE_KEY.encode()).hexdigest(),
            hmac_secret=secrets.token_hex(32),
        )
    )
    db_session.commit()


def _stored_measurement_run_ids(db_session: Session) -> list[str]:
    return list(
        db_session.scalars(
            select(Run.run_id)
            .join(Measurement, Measurement.run_pk == Run.id)
            .order_by(Measurement.id)
        )
    )


def _stored_latency_run_ids(db_session: Session) -> list[str]:
    return list(
        db_session.scalars(
            select(Run.run_id)
            .join(LatencyTestResult, LatencyTestResult.run_pk == Run.id)
            .order_by(LatencyTestResult.id)
        )
    )


def test_measurement_upload_stores_the_device_supplied_run_id(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    response = test_client.post(
        "/measurements", json=[_datapoint(run_id="run-abc")], headers=DEVICE_HEADERS
    )

    assert response.status_code == 200, response.text
    assert _stored_measurement_run_ids(db_session) == ["run-abc"]


def test_measurement_upload_without_run_id_gets_the_legacy_run_id(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    response = test_client.post("/measurements", json=[_datapoint()], headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    assert _stored_measurement_run_ids(db_session) == [f"legacy-{DEVICE_ID}-ground-2026-07-30"]


def test_measurement_upload_rejects_an_invalid_run_id(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    response = test_client.post(
        "/measurements", json=[_datapoint(run_id="bad id; drop table")], headers=DEVICE_HEADERS
    )

    assert response.status_code == 422
    assert _stored_measurement_run_ids(db_session) == []


def test_latency_upload_stores_the_device_supplied_run_id(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    response = test_client.post(
        "/latency-results", json=_latency_result(run_id="run-abc"), headers=DEVICE_HEADERS
    )

    assert response.status_code == 201, response.text
    assert _stored_latency_run_ids(db_session) == ["run-abc"]


def test_latency_upload_without_run_id_gets_the_legacy_run_id_from_the_start_timestamp(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    response = test_client.post(
        "/latency-results", json=_latency_result(), headers=DEVICE_HEADERS
    )

    assert response.status_code == 201, response.text
    assert _stored_latency_run_ids(db_session) == [f"legacy-{DEVICE_ID}-ground-2026-07-30"]


def test_the_same_run_id_from_two_devices_stays_two_separate_runs(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    other_headers = {"X-Device-ID": "other-device", "X-Device-Key": DEVICE_KEY}
    db_session.add(
        Device(
            device_id="other-device",
            api_key_hash=hashlib.sha256(DEVICE_KEY.encode()).hexdigest(),
            hmac_secret=secrets.token_hex(32),
        )
    )
    db_session.commit()

    test_client.post("/measurements", json=[_datapoint(run_id="shared")], headers=DEVICE_HEADERS)
    test_client.post(
        "/measurements",
        json=[_datapoint(run_id="shared", device_id="other-device")],
        headers=other_headers,
    )

    rows = db_session.execute(
        select(Measurement.device_id, Run.run_id).join(Run, Measurement.run_pk == Run.id)
    ).all()
    assert {(row.device_id, row.run_id) for row in rows} == {
        (DEVICE_ID, "shared"),
        ("other-device", "shared"),
    }


def _stored_runs(db_session: Session) -> list[tuple[str, str, int | None]]:
    db_session.expire_all()
    return [
        (run.device_id, run.run_id, run.campaign_id)
        for run in db_session.scalars(select(Run).order_by(Run.id))
    ]


def test_measurement_upload_creates_an_unassigned_run(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    response = test_client.post(
        "/measurements", json=[_datapoint(run_id="run-abc")], headers=DEVICE_HEADERS
    )

    assert response.status_code == 200, response.text
    assert _stored_runs(db_session) == [(DEVICE_ID, "run-abc", None)]


def test_measurement_upload_without_run_id_creates_the_legacy_run(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    test_client.post("/measurements", json=[_datapoint()], headers=DEVICE_HEADERS)

    assert _stored_runs(db_session) == [(DEVICE_ID, f"legacy-{DEVICE_ID}-ground-2026-07-30", None)]


def test_measurement_upload_creates_one_run_per_distinct_run_id_in_the_batch(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    batch = [
        _datapoint(run_id="run-a"),
        _datapoint(run_id="run-a"),
        _datapoint(run_id="run-b"),
    ]

    response = test_client.post("/measurements", json=batch, headers=DEVICE_HEADERS)

    assert response.status_code == 200, response.text
    assert _stored_runs(db_session) == [(DEVICE_ID, "run-a", None), (DEVICE_ID, "run-b", None)]


def test_a_later_upload_of_the_same_run_keeps_the_run_and_its_campaign(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    test_client.post("/measurements", json=[_datapoint(run_id="run-a")], headers=DEVICE_HEADERS)
    campaign = Campaign(name="summer-2026")
    db_session.add(campaign)
    db_session.commit()
    db_session.execute(Run.__table__.update().values(campaign_id=campaign.id))
    db_session.commit()

    response = test_client.post(
        "/measurements", json=[_datapoint(run_id="run-a")], headers=DEVICE_HEADERS
    )

    assert response.status_code == 200, response.text
    assert _stored_runs(db_session) == [(DEVICE_ID, "run-a", campaign.id)]


def test_a_rejected_upload_creates_no_run(test_client: TestClient, db_session: Session):
    _register_device(db_session)

    response = test_client.post(
        "/measurements", json=[_datapoint(run_id="bad id; drop table")], headers=DEVICE_HEADERS
    )

    assert response.status_code == 422
    assert _stored_runs(db_session) == []


# --- Run attributes ----------------------------------------------------------


def _only_run(db_session: Session) -> Run:
    db_session.expire_all()
    return db_session.scalars(select(Run)).one()


def test_measurement_upload_stores_the_datapoint_mission_type_on_a_new_run(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    test_client.post(
        "/measurements",
        json=[_datapoint(run_id="run-a", mission_type="drone")],
        headers=DEVICE_HEADERS,
    )

    run = _only_run(db_session)
    assert (run.mission_type, run.name) == ("drone", None)


def test_a_later_upload_does_not_overwrite_the_edited_attributes_of_the_run(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    test_client.post("/measurements", json=[_datapoint(run_id="run-a")], headers=DEVICE_HEADERS)
    db_session.execute(Run.__table__.update().values(mission_type="drone", name="Flight 1"))
    db_session.commit()

    response = test_client.post(
        "/measurements",
        json=[_datapoint(run_id="run-a", mission_type="ground")],
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 200, response.text
    run = _only_run(db_session)
    assert (run.mission_type, run.name) == ("drone", "Flight 1")
    assert db_session.scalars(select(Measurement.run_pk)).all() == [run.id, run.id]


def test_a_latency_upload_does_not_overwrite_the_edited_attributes_of_the_run(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)
    test_client.post("/measurements", json=[_datapoint(run_id="run-a")], headers=DEVICE_HEADERS)
    db_session.execute(Run.__table__.update().values(mission_type="drone"))
    db_session.commit()

    response = test_client.post(
        "/latency-results",
        json=_latency_result(run_id="run-a", mission_type="ground"),
        headers=DEVICE_HEADERS,
    )

    assert response.status_code == 201, response.text
    run = _only_run(db_session)
    assert run.mission_type == "drone"
    assert db_session.scalars(select(LatencyTestResult.run_pk)).all() == [run.id]


def test_a_latency_upload_without_measurements_creates_its_run(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    test_client.post(
        "/latency-results",
        json=_latency_result(run_id="run-a", mission_type="drone"),
        headers=DEVICE_HEADERS,
    )

    run = _only_run(db_session)
    assert (run.device_id, run.run_id, run.mission_type) == (DEVICE_ID, "run-a", "drone")


def test_measurements_and_latency_results_of_one_run_share_it(
    test_client: TestClient, db_session: Session
):
    _register_device(db_session)

    test_client.post("/measurements", json=[_datapoint(run_id="run-a")], headers=DEVICE_HEADERS)
    test_client.post(
        "/latency-results", json=_latency_result(run_id="run-a"), headers=DEVICE_HEADERS
    )

    run = _only_run(db_session)
    assert db_session.scalars(select(Measurement.run_pk)).all() == [run.id]
    assert db_session.scalars(select(LatencyTestResult.run_pk)).all() == [run.id]
