"""Integration tests for campaigns defined by their assigned runs: which rows the
public and authenticated map/export/latency queries reach is decided by `Run.campaign_id`, never
by timestamps.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Device
from app.models.latency import LatencyTestResult
from app.models.measurement import Measurement
from tests.integration.campaign_helpers import assign_runs, create_campaign
from tests.integration.run_helpers import run_row
from tests.integration.test_api.test_measurements_detailed import _auth_headers

BERLIN_BBOX = "13.0,52.0,13.5,52.5"
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

HEATMAP_URL = "/measurements/heatmap"
EXTENT_URL = "/measurements/extent"
POINTS_URL = "/measurements/points"
EXPORT_URL = "/measurements/export"
DETAILED_URL = "/measurements/detailed"
LATENCY_HEATMAP_URL = "/latency-results/heatmap"
LATENCY_POINTS_URL = "/latency-results/points"
LATENCY_RAW_URL = "/latency-results/raw"


def _measurement(
    run_id: str, rsrp: float, timestamp: datetime = NOW, lat: float = 52.1
) -> Measurement:
    return run_row(
        Measurement,
        timestamp=timestamp,
        device_id="device-1",
        mission_type="ground",
        run_id=run_id,
        latitude=lat,
        longitude=13.1,
        placeholder=False,
        rsrp=rsrp,
        rsrq=-10.0,
        sinr=12.0,
        rat="LTE",
        raw_data={},
    )


def _latency_result(run_id: str, rtt: float, timestamp: datetime = NOW) -> LatencyTestResult:
    fix = {"position": {"latitude": 52.1, "longitude": 13.1}, "placeholder": False}
    return run_row(
        LatencyTestResult,
        device_id="device-1",
        test_type="baseline",
        flent_test="rrul",
        mission_type="ground",
        run_id=run_id,
        start_timestamp=timestamp,
        end_timestamp=timestamp,
        start_fix=fix,
        end_fix=fix,
        baseline_rtt_ms=rtt,
        idempotency_key=f"{run_id}-{rtt}",
    )


def _add(db_session: Session, *rows) -> None:
    if db_session.get(Device, "device-1") is None:
        db_session.add(Device(device_id="device-1", api_key_hash="x", hmac_secret="x"))
        db_session.flush()
    db_session.add_all(rows)
    db_session.commit()


def _values(response) -> list[float]:
    assert response.status_code == 200, response.text
    return sorted(f["properties"]["value"] for f in response.json()["features"])


def _heatmap(test_client, **params) -> list[float]:
    query = {"bbox": BERLIN_BBOX, "metric": "rsrp", **params}
    return _values(test_client.get(HEATMAP_URL, params=query))


def test_campaign_contains_exactly_its_assigned_runs_regardless_of_timestamps(
    test_client, db_session
):
    campaign = create_campaign(db_session, "chosen")
    _add(
        db_session,
        _measurement("assigned-old", -90.0, NOW - timedelta(days=400), lat=52.1),
        _measurement("assigned-new", -80.0, NOW, lat=52.3),
        _measurement("between", -70.0, NOW - timedelta(days=200), lat=52.2),
    )
    assign_runs(db_session, campaign, ("device-1", "assigned-old"), ("device-1", "assigned-new"))

    assert _heatmap(test_client, campaign_id=campaign.id) == [-90.0, -80.0]


def test_runs_of_other_campaigns_and_unassigned_runs_are_not_reachable(test_client, db_session):
    first = create_campaign(db_session, "first")
    second = create_campaign(db_session, "second")
    _add(
        db_session,
        _measurement("run-1", -90.0, lat=52.1),
        _measurement("run-2", -70.0, lat=52.2),
        _measurement("run-unassigned", -50.0, lat=52.3),
    )
    assign_runs(db_session, first, ("device-1", "run-1"))
    assign_runs(db_session, second, ("device-1", "run-2"))

    assert _heatmap(test_client, campaign_id=first.id) == [-90.0]
    assert _heatmap(test_client, campaign_id=second.id) == [-70.0]


def test_same_run_id_on_another_device_is_not_part_of_the_campaign(test_client, db_session):
    campaign = create_campaign(db_session, "chosen")
    other_device_row = _measurement("shared-run", -50.0, lat=52.3)
    other_device_row.device_id = "device-2"
    _add(db_session, _measurement("shared-run", -90.0, lat=52.1), other_device_row)
    assign_runs(db_session, campaign, ("device-1", "shared-run"))

    assert _heatmap(test_client, campaign_id=campaign.id) == [-90.0]


def test_default_campaign_is_the_one_with_the_most_recent_run_end(test_client, db_session):
    older = create_campaign(db_session, "older")
    newer = create_campaign(db_session, "newer")
    _add(
        db_session,
        _measurement("run-old", -90.0, NOW - timedelta(days=30), lat=52.1),
        _measurement("run-new", -70.0, NOW, lat=52.2),
        # a long run that started early but ended last decides, not the start
        _measurement("run-long", -60.0, NOW - timedelta(days=60), lat=52.3),
        _measurement("run-long", -61.0, NOW + timedelta(days=1), lat=52.4),
    )
    assign_runs(db_session, older, ("device-1", "run-old"), ("device-1", "run-long"))
    assign_runs(db_session, newer, ("device-1", "run-new"))

    assert _heatmap(test_client) == [-90.0, -61.0, -60.0]


def test_default_campaign_never_falls_back_to_unassigned_data(test_client, db_session):
    create_campaign(db_session, "empty")
    _add(db_session, _measurement("run-unassigned", -90.0))

    assert _heatmap(test_client) == []
    extent = test_client.get(EXTENT_URL, params={"metric": "rsrp"})
    assert extent.status_code == 200
    assert extent.json()["bbox"] is None
    points = test_client.get(POINTS_URL, params={"bbox": BERLIN_BBOX, "metric": "rsrp"})
    assert points.json()["features"] == []
    export = test_client.get(
        EXPORT_URL, params={"bbox": BERLIN_BBOX, "metric": "rsrp", "format": "csv"}
    )
    assert export.text.strip().splitlines() == ["latitude,longitude,rsrp,count"]


def test_default_campaign_skips_campaigns_without_runs(test_client, db_session):
    with_runs = create_campaign(db_session, "with-runs")
    create_campaign(db_session, "created-later-but-empty")
    _add(db_session, _measurement("run-1", -90.0))
    assign_runs(db_session, with_runs, ("device-1", "run-1"))

    assert _heatmap(test_client) == [-90.0]


def test_unknown_campaign_is_still_a_404(test_client):
    response = test_client.get(
        HEATMAP_URL, params={"bbox": BERLIN_BBOX, "metric": "rsrp", "campaign_id": 999999}
    )

    assert response.status_code == 404


def test_extent_points_and_export_use_the_assigned_runs(test_client, db_session):
    campaign = create_campaign(db_session, "chosen")
    _add(
        db_session,
        _measurement("in", -90.0, lat=52.1),
        _measurement("out", -70.0, lat=52.4),
    )
    assign_runs(db_session, campaign, ("device-1", "in"))
    params = {"metric": "rsrp", "campaign_id": campaign.id}

    extent = test_client.get(EXTENT_URL, params=params).json()["bbox"]
    points = test_client.get(POINTS_URL, params={"bbox": BERLIN_BBOX, **params}).json()
    export = test_client.get(
        EXPORT_URL, params={"bbox": BERLIN_BBOX, "format": "csv", **params}
    )

    assert extent == [13.1, 52.1, 13.1, 52.1]
    assert len(points["features"]) == 1
    assert len(export.text.strip().splitlines()) == 2


def test_authenticated_view_without_campaign_still_means_all_time_including_unassigned(
    test_client, db_session
):
    headers = _auth_headers(db_session, test_client)
    campaign = create_campaign(db_session, "chosen")
    _add(db_session, _measurement("in", -90.0, lat=52.1), _measurement("out", -70.0, lat=52.2))
    assign_runs(db_session, campaign, ("device-1", "in"))
    params = {"bbox": BERLIN_BBOX, "metric": "rsrp", "view": "raw"}

    everything = test_client.get(DETAILED_URL, params=params, headers=headers)
    scoped = test_client.get(
        DETAILED_URL, params={**params, "campaign_id": campaign.id}, headers=headers
    )

    assert len(everything.json()["features"]) == 2
    assert len(scoped.json()["features"]) == 1


def test_latency_results_follow_the_assigned_runs(test_client, db_session):
    first = create_campaign(db_session, "first")
    second = create_campaign(db_session, "second")
    _add(
        db_session,
        _measurement("run-1", -90.0),
        _measurement("run-2", -90.0, NOW + timedelta(days=1)),
        _latency_result("run-1", 40.0),
        _latency_result("run-2", 80.0, NOW + timedelta(days=1)),
        _latency_result("run-unassigned", 99.0),
    )
    assign_runs(db_session, first, ("device-1", "run-1"))
    assign_runs(db_session, second, ("device-1", "run-2"))
    params = {"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"}

    def heatmap_values(**extra) -> list[float]:
        return _values(test_client.get(LATENCY_HEATMAP_URL, params={**params, **extra}))

    assert heatmap_values(campaign_id=first.id) == [40.0]
    assert heatmap_values(campaign_id=second.id) == [80.0]
    # default: second has the most recent run end; the unassigned result is never reachable
    assert heatmap_values() == [80.0]
    public_points = test_client.get(LATENCY_POINTS_URL, params=params).json()["features"]
    assert [f["properties"]["baseline_rtt_ms"] for f in public_points] == [80.0]


def test_latency_raw_view_scopes_to_the_campaign_runs(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    campaign = create_campaign(db_session, "chosen")
    _add(db_session, _latency_result("run-1", 40.0), _latency_result("run-2", 80.0))
    assign_runs(db_session, campaign, ("device-1", "run-1"))
    params = {"bbox": BERLIN_BBOX, "metric": "baseline_rtt_ms"}

    scoped = test_client.get(
        LATENCY_RAW_URL, params={**params, "campaign_id": campaign.id}, headers=headers
    )
    everything = test_client.get(LATENCY_RAW_URL, params=params, headers=headers)

    assert [f["properties"]["baseline_rtt_ms"] for f in scoped.json()["features"]] == [40.0]
    assert len(everything.json()["features"]) == 2
