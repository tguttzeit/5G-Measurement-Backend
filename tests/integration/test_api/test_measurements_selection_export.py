"""Integration tests for `POST /measurements/export-selection`: export of selected
map points with only position, metrics, mission type and campaign name.

Needs a real Postgres - see tests/integration/conftest.py and test_measurements_detailed.py
for the fixtures and row helpers reused here.
"""

import csv
import io
from datetime import UTC, datetime

from tests.integration.campaign_helpers import assign_runs, create_campaign
from tests.integration.run_helpers import assign_run_id
from tests.integration.test_api.test_measurements_detailed import (
    BERLIN_BBOX,
    _auth_headers,
    _measurement,
)

URL = "/measurements/export-selection"
EXPORT_COLUMNS = ["latitude", "longitude", "rsrp", "rsrq", "sinr", "mission_type", "campaign"]
FORBIDDEN_KEYS = {"id", "device_id", "timestamp", "run_id", "raw_data", "start", "end"}


def _add(db_session, *measurements):
    db_session.add_all(measurements)
    db_session.commit()
    return [measurement.id for measurement in measurements]


def _in_campaign(db_session, name, *measurements, run_id="run-1"):
    for measurement in measurements:
        assign_run_id(measurement, run_id)
    campaign = create_campaign(db_session, name)
    ids = _add(db_session, *measurements)
    assign_runs(db_session, campaign, *{(m.device_id, run_id) for m in measurements})
    return ids


def _csv_rows(response):
    return list(csv.DictReader(io.StringIO(response.text)))


def test_guest_csv_contains_only_the_listed_columns(test_client, db_session):
    ids = _in_campaign(db_session, "berlin", _measurement(52.1, 13.1, device_id="secret-device"))

    response = test_client.post(URL, json={"ids": ids, "format": "csv"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.splitlines()[0] == ",".join(EXPORT_COLUMNS)
    assert _csv_rows(response) == [
        {
            "latitude": "52.1",
            "longitude": "13.1",
            "rsrp": "-95.0",
            "rsrq": "-10.0",
            "sinr": "12.0",
            "mission_type": "ground",
            "campaign": "berlin",
        }
    ]
    assert "secret-device" not in response.text
    assert "must-never-leak" not in response.text


def test_guest_geojson_contains_only_the_listed_properties(test_client, db_session):
    ids = _in_campaign(db_session, "berlin", _measurement(52.1, 13.1, device_id="secret-device"))

    response = test_client.post(URL, json={"ids": ids, "format": "geojson"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/geo+json")
    [feature] = response.json()["features"]
    assert feature["geometry"] == {"type": "Point", "coordinates": [13.1, 52.1]}
    assert feature["properties"] == {
        "rsrp": -95.0,
        "rsrq": -10.0,
        "sinr": 12.0,
        "mission_type": "ground",
        "campaign": "berlin",
    }
    assert FORBIDDEN_KEYS.isdisjoint(feature["properties"])
    assert "secret-device" not in response.text


def test_guest_cannot_reach_measurements_of_unassigned_runs(test_client, db_session):
    [assigned_id] = _in_campaign(db_session, "berlin", _measurement(52.1, 13.1))
    [unassigned_id] = _add(db_session, _measurement(52.2, 13.2, device_id="other-device"))

    response = test_client.post(URL, json={"ids": [assigned_id, unassigned_id], "format": "csv"})

    assert [row["latitude"] for row in _csv_rows(response)] == ["52.1"]


def test_unassigned_and_unknown_ids_are_indistinguishable_for_guests(test_client, db_session):
    [unassigned_id] = _add(db_session, _measurement(52.2, 13.2))
    unknown_id = unassigned_id + 1000

    unassigned = test_client.post(URL, json={"ids": [unassigned_id], "format": "csv"})
    unknown = test_client.post(URL, json={"ids": [unknown_id], "format": "csv"})

    assert unassigned.status_code == unknown.status_code == 200
    assert unassigned.text == unknown.text
    assert _csv_rows(unassigned) == []


def test_authenticated_user_can_export_unassigned_points_with_empty_campaign(
    test_client, db_session
):
    [unassigned_id] = _add(db_session, _measurement(52.2, 13.2))
    headers = _auth_headers(db_session, test_client)

    csv_response = test_client.post(
        URL, json={"ids": [unassigned_id], "format": "csv"}, headers=headers
    )
    geojson_response = test_client.post(
        URL, json={"ids": [unassigned_id], "format": "geojson"}, headers=headers
    )

    assert _csv_rows(csv_response)[0]["campaign"] == ""
    assert geojson_response.json()["features"][0]["properties"]["campaign"] is None


def test_invalid_token_is_treated_as_guest(test_client, db_session):
    [unassigned_id] = _add(db_session, _measurement(52.2, 13.2))

    response = test_client.post(
        URL,
        json={"ids": [unassigned_id], "format": "csv"},
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert _csv_rows(response) == []


def test_placeholder_rows_are_skipped(test_client, db_session):
    ids = _in_campaign(
        db_session,
        "berlin",
        _measurement(52.1, 13.1),
        _measurement(0.0, 0.0, placeholder=True),
    )

    response = test_client.post(URL, json={"ids": ids, "format": "csv"})

    assert [row["latitude"] for row in _csv_rows(response)] == ["52.1"]


def test_missing_metric_values_are_exported_as_empty_cells(test_client, db_session):
    ids = _in_campaign(db_session, "berlin", _measurement(52.1, 13.1, rsrp=None))

    response = test_client.post(URL, json={"ids": ids, "format": "csv"})

    assert _csv_rows(response)[0]["rsrp"] == ""


def test_duplicate_ids_yield_one_row(test_client, db_session):
    ids = _in_campaign(db_session, "berlin", _measurement(52.1, 13.1))

    response = test_client.post(URL, json={"ids": ids * 3, "format": "csv"})

    assert len(_csv_rows(response)) == 1


def test_text_cells_cannot_inject_spreadsheet_formulas(test_client, db_session):
    measurement = _measurement(52.1, 13.1, mission_type="=HYPERLINK(\"http://evil\")")
    ids = _in_campaign(db_session, "berlin", measurement)

    response = test_client.post(URL, json={"ids": ids, "format": "csv"})

    assert _csv_rows(response)[0]["mission_type"].startswith("'=")


def test_only_the_run_campaign_name_is_used(test_client, db_session):
    first = _in_campaign(db_session, "first", _measurement(52.1, 13.1), run_id="run-a")
    second = _in_campaign(db_session, "second", _measurement(52.2, 13.2), run_id="run-b")

    response = test_client.post(URL, json={"ids": first + second, "format": "csv"})

    assert [row["campaign"] for row in _csv_rows(response)] == ["first", "second"]


def test_raw_points_expose_the_measurement_id(test_client, db_session):
    [measurement_id] = _in_campaign(db_session, "berlin", _measurement(52.1, 13.1))
    headers = _auth_headers(db_session, test_client)
    params = {"bbox": BERLIN_BBOX, "metric": "rsrp"}

    public = test_client.get("/measurements/points", params=params)
    detailed = test_client.get(
        "/measurements/detailed", params={**params, "view": "raw"}, headers=headers
    )

    assert public.json()["features"][0]["properties"]["id"] == measurement_id
    assert detailed.json()["features"][0]["properties"]["id"] == measurement_id


def test_timestamp_of_selected_points_is_not_leaked(test_client, db_session):
    ids = _in_campaign(
        db_session,
        "berlin",
        _measurement(52.1, 13.1, timestamp=datetime(2031, 3, 4, tzinfo=UTC)),
    )

    response = test_client.post(URL, json={"ids": ids, "format": "geojson"})

    assert "2031" not in response.text
