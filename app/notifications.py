"""Opt-in push notifications for device events.

Events are detected at ingestion by comparing a heartbeat with the previous one. Matching
users are looked up while the request's session is open; the delivery itself runs as a
background task so a slow ntfy server never delays the device's response.
"""

import json
import logging
import secrets
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import UserNotificationSettings
from app.models.user import User
from app.schemas.heartbeat import RunPhase
from app.schemas.notifications import NotificationEvent

logger = logging.getLogger(__name__)

# A heartbeat after this many silent heartbeat intervals counts as the box having (re)started.
# Large enough that a few lost heartbeats are not mistaken for a restart, small enough that a
# reboot (about a minute) is still caught.
BOX_STARTED_GAP_INTERVALS = 3

_NTFY_TIMEOUT_S = 5

_EVENT_TEXTS = {
    NotificationEvent.BOX_STARTED: "Measurement box started",
    NotificationEvent.MEASUREMENT_STARTED: "Measurement started",
    NotificationEvent.MEASUREMENT_FINISHED: "Measurement finished",
    NotificationEvent.RUNS_UPLOADED: "New runs uploaded",
    NotificationEvent.ERROR: "Error",
}

_TOPIC_BYTES = 24


def new_topic() -> str:
    return secrets.token_urlsafe(_TOPIC_BYTES)


@dataclass(frozen=True)
class Notification:
    title: str
    message: str


class NotificationChannel(Protocol):
    def send(self, topics: Iterable[str], notification: Notification) -> None: ...


class NtfyChannel:
    """Publishes through ntfy's JSON endpoint, so topic and text travel in the request body and
    never in a URL or header."""

    def __init__(self, base_url: str, access_token: str | None) -> None:
        self._url = base_url.rstrip("/")
        self._access_token = access_token

    def send(self, topics: Iterable[str], notification: Notification) -> None:
        for topic in topics:
            body = json.dumps(
                {"topic": topic, "title": notification.title, "message": notification.message}
            ).encode("utf-8")
            request = urllib.request.Request(  # noqa: S310 - URL comes from server config only
                self._url, data=body, method="POST"
            )
            request.add_header("Content-Type", "application/json")
            if self._access_token:
                request.add_header("Authorization", f"Bearer {self._access_token}")
            try:
                with urllib.request.urlopen(request, timeout=_NTFY_TIMEOUT_S):  # noqa: S310
                    pass
            except Exception as exc:
                # Only the exception type: its message can echo the request, which holds the topic.
                logger.warning("ntfy delivery failed: %s", type(exc).__name__)


def get_notification_channel() -> NotificationChannel:
    """FastAPI dependency; tests override it with a fake channel."""
    settings = get_settings()
    return NtfyChannel(settings.ntfy_base_url, settings.ntfy_access_token)


def build_notification(event: NotificationEvent, device_id: str, at: datetime) -> Notification:
    return Notification(
        title=f"5GM {device_id}",
        message=f"{_EVENT_TEXTS[event]} ({at.astimezone(UTC):%Y-%m-%d %H:%M} UTC)",
    )


def detect_heartbeat_events(
    *,
    previous_run_phase: str | None,
    previous_pipeline_broken: bool,
    previous_received_at: datetime,
    heartbeat_interval_s: float,
    received_at: datetime,
    run_phase: RunPhase | None,
    pipeline_broken: bool,
    failed_command_ack: bool,
) -> set[NotificationEvent]:
    """Events a heartbeat signals relative to the device's previous one; only transitions count,
    so a state that merely persists notifies once."""
    events: set[NotificationEvent] = set()

    gap_s = (received_at - previous_received_at).total_seconds()
    if gap_s > BOX_STARTED_GAP_INTERVALS * heartbeat_interval_s:
        events.add(NotificationEvent.BOX_STARTED)

    measuring = RunPhase.ACTIVE_MEASURING.value
    now_phase = run_phase.value if run_phase is not None else None
    if now_phase == measuring and previous_run_phase != measuring:
        events.add(NotificationEvent.MEASUREMENT_STARTED)
    if previous_run_phase == measuring and now_phase != measuring:
        events.add(NotificationEvent.MEASUREMENT_FINISHED)

    critical = RunPhase.CRITICAL_ERROR.value
    if (
        (now_phase == critical and previous_run_phase != critical)
        or (pipeline_broken and not previous_pipeline_broken)
        or failed_command_ack
    ):
        events.add(NotificationEvent.ERROR)

    return events


def subscribed_topics(db: Session, event: NotificationEvent) -> list[str]:
    rows = db.execute(
        select(UserNotificationSettings.topic, UserNotificationSettings.events)
        .join(User, User.id == UserNotificationSettings.user_id)
        .where(UserNotificationSettings.enabled.is_(True), User.is_active.is_(True))
    ).all()
    return [topic for topic, events in rows if event.value in events]


def prepare_notifications(
    db: Session, events: Iterable[NotificationEvent], device_id: str, at: datetime
) -> list[tuple[list[str], Notification]]:
    """Resolve recipients now, while the session is open; send the result via `deliver`."""
    prepared = []
    for event in events:
        topics = subscribed_topics(db, event)
        if topics:
            prepared.append((topics, build_notification(event, device_id, at)))
    return prepared


def deliver(
    channel: NotificationChannel, prepared: list[tuple[list[str], Notification]]
) -> None:
    for topics, notification in prepared:
        try:
            channel.send(topics, notification)
        except Exception as exc:
            logger.warning("Notification delivery failed: %s", type(exc).__name__)
