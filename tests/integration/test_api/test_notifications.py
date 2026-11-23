"""Integration tests for the opt-in notification settings endpoints and for the notifications
fired from heartbeat and upload ingestion. A fake channel replaces ntfy, so nothing
touches the network."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.main import app
from app.models import CommandType, DeviceCommand, Heartbeat, UserNotificationSettings
from app.models.user import User
from app.notifications import Notification, get_notification_channel
from app.routers import notification_settings as notification_settings_router
from app.schemas.notifications import NotificationEvent
from tests.integration.test_api.test_heartbeat import (
    DEVICE_HEADERS,
    HEARTBEAT_URL,
    KNOWN_DEVICE_ID,
    VALID_HEARTBEAT_BODY,
    _register_device,
)
from tests.integration.test_api.test_measurements_detailed import _auth_headers
from tests.integration.test_api.test_upload_stream import (
    DEVICE_HEADERS as UPLOAD_DEVICE_HEADERS,
)
from tests.integration.test_api.test_upload_stream import (
    VALID_DATAPOINT,
)
from tests.integration.test_api.test_upload_stream import (
    _register_device as _register_upload_device,
)

URL = "/notification-settings"
ALL_EVENTS = [event.value for event in NotificationEvent]


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[tuple[list[str], Notification]] = []

    def send(self, topics, notification) -> None:
        self.sent.append((list(topics), notification))

    @property
    def messages(self) -> list[str]:
        return [notification.message for _, notification in self.sent]


@pytest.fixture
def channel():
    fake = FakeChannel()
    app.dependency_overrides[get_notification_channel] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_notification_channel, None)


@pytest.fixture(autouse=True)
def _reset_test_rate_limit():
    notification_settings_router._last_test_sent.clear()


def _subscribe(test_client, db_session, username: str, events: list[str], enabled: bool = True):
    headers = _auth_headers(db_session, test_client, username)
    response = test_client.put(URL, json={"enabled": enabled, "events": events}, headers=headers)
    assert response.status_code == 200, response.text
    return headers, response.json()["topic"]


def _store_heartbeat(db_session: Session, age: timedelta = timedelta(seconds=60), **fields):
    db_session.add(
        Heartbeat(
            device_id=KNOWN_DEVICE_ID,
            received_at=datetime.now(UTC) - age,
            datapoints_total=0,
            datapoints_valid=0,
            datapoints_invalid=0,
            pipeline_broken=fields.pop("pipeline_broken", False),
            storage_pending_files=0,
            storage_disk_free_bytes=1,
            **fields,
        )
    )
    db_session.commit()


def _beat(test_client, **overrides):
    response = test_client.post(
        HEARTBEAT_URL, json={**VALID_HEARTBEAT_BODY, **overrides}, headers=DEVICE_HEADERS
    )
    assert response.status_code == 200, response.text


# --- Settings endpoints ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", ""), ("put", ""), ("post", "/regenerate-topic"), ("post", "/test")],
)
def test_endpoints_require_auth(test_client, method, path):
    kwargs = {"json": {"enabled": True, "events": []}} if method == "put" else {}

    assert getattr(test_client, method)(URL + path, **kwargs).status_code == 401


def test_get_defaults_to_disabled_without_events_and_returns_topic_and_server(
    test_client, db_session
):
    headers = _auth_headers(db_session, test_client)

    body = test_client.get(URL, headers=headers).json()

    assert body["enabled"] is False
    assert body["events"] == []
    assert body["server_url"] == "https://ntfy.sh"
    assert len(body["topic"]) >= 22


def test_topic_is_stable_across_reads_and_puts_and_disabling(test_client, db_session):
    headers = _auth_headers(db_session, test_client)
    topic = test_client.get(URL, headers=headers).json()["topic"]

    on = test_client.put(URL, json={"enabled": True, "events": ALL_EVENTS}, headers=headers)
    off = test_client.put(URL, json={"enabled": False, "events": []}, headers=headers)
    again = test_client.put(URL, json={"enabled": True, "events": ["error"]}, headers=headers)

    assert [r.json()["topic"] for r in (on, off, again)] == [topic] * 3
    assert test_client.get(URL, headers=headers).json()["topic"] == topic


def test_put_stores_enabled_and_deduplicated_events(test_client, db_session):
    headers = _auth_headers(db_session, test_client)

    body = test_client.put(
        URL, json={"enabled": True, "events": ["error", "error", "box_started"]}, headers=headers
    ).json()

    assert body["enabled"] is True
    assert body["events"] == ["error", "box_started"]
    assert test_client.get(URL, headers=headers).json()["events"] == ["error", "box_started"]


@pytest.mark.parametrize(
    "body",
    [
        {"enabled": True, "events": ["nope"]},
        {"enabled": "yes", "events": []},
        {"enabled": True, "events": [], "topic": "mine"},
    ],
)
def test_put_rejects_invalid_input(test_client, db_session, body):
    headers = _auth_headers(db_session, test_client)

    assert test_client.put(URL, json=body, headers=headers).status_code == 422


def test_settings_are_isolated_per_user(test_client, db_session):
    alice, alice_topic = _subscribe(test_client, db_session, "alice", ["error"])
    bob = _auth_headers(db_session, test_client, "bob")

    bob_view = test_client.get(URL, headers=bob).json()
    regenerated = test_client.post(f"{URL}/regenerate-topic", headers=bob).json()

    assert bob_view["enabled"] is False
    assert bob_view["topic"] != alice_topic
    assert regenerated["topic"] != alice_topic
    assert test_client.get(URL, headers=alice).json()["topic"] == alice_topic
    assert test_client.get(URL, headers=alice).json()["events"] == ["error"]


def test_regenerate_topic_replaces_topic_and_keeps_other_settings(test_client, db_session):
    headers, topic = _subscribe(test_client, db_session, "alice", ["error"])

    body = test_client.post(f"{URL}/regenerate-topic", headers=headers).json()

    assert body["topic"] != topic
    assert body["enabled"] is True
    assert body["events"] == ["error"]


def test_old_topic_stops_receiving_after_regeneration(test_client, db_session, channel):
    headers, old_topic = _subscribe(test_client, db_session, "alice", ["error"])
    new_topic = test_client.post(f"{URL}/regenerate-topic", headers=headers).json()["topic"]
    _register_device(db_session)
    _store_heartbeat(db_session)

    _beat(test_client, pipeline_broken=True)

    assert [topics for topics, _ in channel.sent] == [[new_topic]]
    assert old_topic != new_topic


def test_deleting_a_user_removes_their_settings(test_client, db_session):
    _subscribe(test_client, db_session, "bob", ["error"])
    bob = db_session.query(User).filter_by(email="bob").one()

    db_session.delete(bob)
    db_session.commit()

    assert db_session.query(UserNotificationSettings).count() == 0


def test_test_endpoint_sends_to_the_callers_topic_only(test_client, db_session, channel):
    headers, topic = _subscribe(test_client, db_session, "alice", [])
    _subscribe(test_client, db_session, "bob", [])

    response = test_client.post(f"{URL}/test", headers=headers)

    assert response.status_code == 202
    assert [topics for topics, _ in channel.sent] == [[topic]]
    assert channel.messages == ["Test notification"]


def test_test_endpoint_is_rate_limited_per_user(test_client, db_session, channel):
    alice, _ = _subscribe(test_client, db_session, "alice", [])
    bob, _ = _subscribe(test_client, db_session, "bob", [])

    first = test_client.post(f"{URL}/test", headers=alice)
    second = test_client.post(f"{URL}/test", headers=alice)
    other_user = test_client.post(f"{URL}/test", headers=bob)

    assert (first.status_code, second.status_code, other_user.status_code) == (202, 429, 202)
    assert int(second.headers["Retry-After"]) >= 1
    assert len(channel.sent) == 2


# --- Detection at ingestion -----------------------------------------------------------


def test_nobody_is_notified_by_default(test_client, db_session, channel):
    _auth_headers(db_session, test_client, "alice")
    _register_device(db_session)
    _store_heartbeat(db_session)

    _beat(test_client, pipeline_broken=True, run_phase="active_measuring")

    assert channel.sent == []


def test_disabled_user_is_not_notified_even_with_events_selected(
    test_client, db_session, channel
):
    _subscribe(test_client, db_session, "alice", ALL_EVENTS, enabled=False)
    _register_device(db_session)
    _store_heartbeat(db_session)

    _beat(test_client, pipeline_broken=True)

    assert channel.sent == []


def test_only_users_who_selected_the_event_are_notified(test_client, db_session, channel):
    _, errors_topic = _subscribe(test_client, db_session, "alice", ["error"])
    _subscribe(test_client, db_session, "bob", ["box_started"])
    _register_device(db_session)
    _store_heartbeat(db_session)

    _beat(test_client, pipeline_broken=True)

    assert [topics for topics, _ in channel.sent] == [[errors_topic]]
    notification = channel.sent[0][1]
    assert notification.title == f"5GM {KNOWN_DEVICE_ID}"
    assert notification.message.startswith("Error (")


def test_inactive_user_is_not_notified(test_client, db_session, channel):
    _subscribe(test_client, db_session, "alice", ["error"])
    db_session.query(User).filter_by(email="alice").update({"is_active": False})
    db_session.commit()
    _register_device(db_session)
    _store_heartbeat(db_session)

    _beat(test_client, pipeline_broken=True)

    assert channel.sent == []


def test_box_started_after_a_long_gap(test_client, db_session, channel):
    _subscribe(test_client, db_session, "alice", ["box_started"])
    _register_device(db_session)
    _store_heartbeat(db_session, age=timedelta(minutes=30))

    _beat(test_client)

    assert channel.messages[0].startswith("Measurement box started")


def test_regular_heartbeat_does_not_notify(test_client, db_session, channel):
    _subscribe(test_client, db_session, "alice", ALL_EVENTS)
    _register_device(db_session)
    _store_heartbeat(db_session)

    _beat(test_client)

    assert channel.sent == []


def test_first_ever_heartbeat_does_not_notify(test_client, db_session, channel):
    _subscribe(test_client, db_session, "alice", ALL_EVENTS)
    _register_device(db_session)

    _beat(test_client, run_phase="active_measuring", pipeline_broken=True)

    assert channel.sent == []


def test_measurement_started_and_finished_follow_run_phase_changes(
    test_client, db_session, channel
):
    _subscribe(test_client, db_session, "alice", ALL_EVENTS)
    _register_device(db_session)
    _store_heartbeat(db_session, run_phase="manual_mode_idle")

    _beat(test_client, run_phase="active_measuring")
    _beat(test_client, run_phase="active_measuring")
    _beat(test_client, run_phase="finalizing")

    assert [m.split(" (")[0] for m in channel.messages] == [
        "Measurement started",
        "Measurement finished",
    ]


def test_critical_error_phase_notifies_once_without_details(test_client, db_session, channel):
    _subscribe(test_client, db_session, "alice", ["error"])
    _register_device(db_session)
    _store_heartbeat(db_session, run_phase="manual_mode_idle")
    critical = {
        "fingerprint": "secret_internal_function",
        "same_error_count": 3,
        "consecutive_reboots": 2,
        "action": "maintenance",
    }

    _beat(test_client, run_phase="critical_error", critical_error=critical)
    _beat(test_client, run_phase="critical_error", critical_error=critical)

    assert len(channel.sent) == 1
    assert "secret_internal_function" not in str(channel.sent)


def test_pipeline_broken_notifies_on_the_rising_edge_only(test_client, db_session, channel):
    _subscribe(test_client, db_session, "alice", ["error"])
    _register_device(db_session)
    _store_heartbeat(db_session)

    _beat(test_client, pipeline_broken=True)
    _beat(test_client, pipeline_broken=True)

    assert len(channel.sent) == 1


def test_failed_command_ack_notifies_without_the_device_error_text(
    test_client, db_session, channel
):
    _subscribe(test_client, db_session, "alice", ["error"])
    _register_device(db_session)
    _store_heartbeat(db_session)
    db_session.add(
        DeviceCommand(
            id=41,
            device_id=KNOWN_DEVICE_ID,
            type=CommandType.ONE_SHOT,
            payload={"command": "reboot-now"},
        )
    )
    db_session.commit()

    _beat(
        test_client,
        executed_commands=[
            {"id": 41, "command": "reboot-now", "status": "failed", "error": "free-form text"}
        ],
    )

    assert len(channel.sent) == 1
    assert "free-form text" not in str(channel.sent)


def test_successful_command_ack_does_not_notify(test_client, db_session, channel):
    _subscribe(test_client, db_session, "alice", ["error"])
    _register_device(db_session)
    _store_heartbeat(db_session)
    db_session.add(
        DeviceCommand(
            id=42,
            device_id=KNOWN_DEVICE_ID,
            type=CommandType.ONE_SHOT,
            payload={"command": "reboot-now"},
        )
    )
    db_session.commit()

    _beat(
        test_client,
        executed_commands=[{"id": 42, "command": "reboot-now", "status": "success"}],
    )

    assert channel.sent == []


def test_heartbeat_succeeds_when_the_channel_raises(test_client, db_session):
    class Exploding:
        def send(self, topics, notification):
            raise RuntimeError("ntfy down")

    app.dependency_overrides[get_notification_channel] = lambda: Exploding()
    try:
        _subscribe(test_client, db_session, "alice", ["error"])
        _register_device(db_session)
        _store_heartbeat(db_session)

        _beat(test_client, pipeline_broken=True)
    finally:
        app.dependency_overrides.pop(get_notification_channel, None)


def test_upload_notifies_subscribers_of_runs_uploaded(test_client, db_session, channel):
    _, topic = _subscribe(test_client, db_session, "alice", ["runs_uploaded"])
    _subscribe(test_client, db_session, "bob", ["error"])
    _register_upload_device(db_session)

    response = test_client.post(
        "/measurements", json=[VALID_DATAPOINT], headers=UPLOAD_DEVICE_HEADERS
    )

    assert response.status_code == 200
    assert [topics for topics, _ in channel.sent] == [[topic]]
    assert channel.messages[0].startswith("New runs uploaded")
