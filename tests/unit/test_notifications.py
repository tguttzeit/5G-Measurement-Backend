"""Unit tests for event detection and the ntfy channel; no database or network."""
import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app import notifications
from app.notifications import (
    BOX_STARTED_GAP_INTERVALS,
    Notification,
    NtfyChannel,
    build_notification,
    deliver,
    detect_heartbeat_events,
)
from app.schemas.heartbeat import RunPhase
from app.schemas.notifications import NotificationEvent, NotificationSettingsUpdate

T0 = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
INTERVAL_S = 60.0


def detect(**overrides) -> set[NotificationEvent]:
    args = {
        "previous_run_phase": RunPhase.MANUAL_MODE_IDLE.value,
        "previous_pipeline_broken": False,
        "previous_received_at": T0,
        "heartbeat_interval_s": INTERVAL_S,
        "received_at": T0 + timedelta(seconds=INTERVAL_S),
        "run_phase": RunPhase.MANUAL_MODE_IDLE,
        "pipeline_broken": False,
        "failed_command_ack": False,
    }
    return detect_heartbeat_events(**{**args, **overrides})


def test_steady_state_notifies_nothing():
    assert detect() == set()


def test_gap_beyond_threshold_is_box_started():
    gap = timedelta(seconds=INTERVAL_S * BOX_STARTED_GAP_INTERVALS + 1)

    assert detect(received_at=T0 + gap) == {NotificationEvent.BOX_STARTED}


def test_gap_at_threshold_is_not_box_started():
    gap = timedelta(seconds=INTERVAL_S * BOX_STARTED_GAP_INTERVALS)

    assert detect(received_at=T0 + gap) == set()


def test_gap_threshold_scales_with_the_device_interval():
    gap = timedelta(seconds=INTERVAL_S * BOX_STARTED_GAP_INTERVALS + 1)

    assert detect(received_at=T0 + gap, heartbeat_interval_s=INTERVAL_S * 2) == set()


def test_entering_active_measuring_is_measurement_started():
    assert detect(run_phase=RunPhase.ACTIVE_MEASURING) == {NotificationEvent.MEASUREMENT_STARTED}


def test_staying_in_active_measuring_notifies_nothing():
    events = detect(
        previous_run_phase=RunPhase.ACTIVE_MEASURING.value, run_phase=RunPhase.ACTIVE_MEASURING
    )

    assert events == set()


@pytest.mark.parametrize("next_phase", [RunPhase.FINALIZING, RunPhase.DONE, None])
def test_leaving_active_measuring_is_measurement_finished(next_phase):
    events = detect(previous_run_phase=RunPhase.ACTIVE_MEASURING.value, run_phase=next_phase)

    assert events == {NotificationEvent.MEASUREMENT_FINISHED}


def test_first_critical_error_heartbeat_is_error():
    assert detect(run_phase=RunPhase.CRITICAL_ERROR) == {NotificationEvent.ERROR}


def test_repeated_critical_error_heartbeat_notifies_nothing():
    events = detect(
        previous_run_phase=RunPhase.CRITICAL_ERROR.value, run_phase=RunPhase.CRITICAL_ERROR
    )

    assert events == set()


def test_pipeline_broken_rising_edge_is_error():
    assert detect(pipeline_broken=True) == {NotificationEvent.ERROR}


def test_pipeline_broken_staying_true_notifies_nothing():
    assert detect(previous_pipeline_broken=True, pipeline_broken=True) == set()


def test_pipeline_broken_falling_edge_notifies_nothing():
    assert detect(previous_pipeline_broken=True, pipeline_broken=False) == set()


def test_failed_command_ack_is_error():
    assert detect(failed_command_ack=True) == {NotificationEvent.ERROR}


def test_several_error_causes_yield_a_single_error_event():
    events = detect(pipeline_broken=True, failed_command_ack=True)

    assert events == {NotificationEvent.ERROR}


def test_message_has_fixed_text_with_device_and_time_only():
    notification = build_notification(NotificationEvent.ERROR, "box-1", T0)

    assert notification == Notification(title="5GM box-1", message="Error (2026-10-30 12:00 UTC)")


def test_update_removes_duplicate_events_keeping_order():
    update = NotificationSettingsUpdate(enabled=True, events=["error", "box_started", "error"])

    assert update.events == [NotificationEvent.ERROR, NotificationEvent.BOX_STARTED]


@pytest.mark.parametrize(
    "body",
    [
        {"enabled": True, "events": ["nope"]},
        {"enabled": "yes", "events": []},
        {"enabled": True, "events": [], "topic": "chosen-by-client"},
        {"events": []},
    ],
)
def test_update_rejects_invalid_bodies(body):
    with pytest.raises(ValidationError):
        NotificationSettingsUpdate(**body)


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_ntfy_posts_json_to_the_server_root_with_bearer_token_and_timeout(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout):
        sent.append((request, timeout))
        return _FakeResponse()

    monkeypatch.setattr(notifications.urllib.request, "urlopen", fake_urlopen)

    NtfyChannel("https://ntfy.example/", "tk_secret").send(
        ["topic-a", "topic-b"], Notification(title="t", message="m")
    )

    assert [json.loads(request.data)["topic"] for request, _ in sent] == ["topic-a", "topic-b"]
    request, timeout = sent[0]
    assert request.full_url == "https://ntfy.example"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer tk_secret"
    assert json.loads(request.data) == {"topic": "topic-a", "title": "t", "message": "m"}
    assert timeout == notifications._NTFY_TIMEOUT_S


def test_ntfy_without_token_sends_no_authorization_header(monkeypatch):
    sent = []
    monkeypatch.setattr(
        notifications.urllib.request,
        "urlopen",
        lambda request, timeout: sent.append(request) or _FakeResponse(),
    )

    NtfyChannel("https://ntfy.example", None).send(["t"], Notification(title="t", message="m"))

    assert sent[0].get_header("Authorization") is None


def test_ntfy_failure_is_logged_without_topic_or_token_and_continues(monkeypatch, caplog):
    calls = []

    def failing_urlopen(request, timeout):
        calls.append(request)
        raise OSError(f"boom {request.data!r} {request.headers!r}")

    monkeypatch.setattr(notifications.urllib.request, "urlopen", failing_urlopen)

    with caplog.at_level(logging.WARNING):
        NtfyChannel("https://ntfy.example", "tk_secret").send(
            ["topic-a", "topic-b"], Notification(title="t", message="m")
        )

    assert len(calls) == 2
    assert "OSError" in caplog.text
    assert "topic-a" not in caplog.text
    assert "tk_secret" not in caplog.text


def test_deliver_survives_a_channel_that_raises(caplog):
    class Exploding:
        def send(self, topics, notification):
            raise RuntimeError("topic-a tk_secret")

    with caplog.at_level(logging.WARNING):
        deliver(Exploding(), [(["topic-a"], Notification(title="t", message="m"))])

    assert "RuntimeError" in caplog.text
    assert "topic-a" not in caplog.text


def test_topics_are_unguessable_and_distinct():
    topics = {notifications.new_topic() for _ in range(50)}

    assert len(topics) == 50
    assert all(len(topic) >= 22 for topic in topics)
