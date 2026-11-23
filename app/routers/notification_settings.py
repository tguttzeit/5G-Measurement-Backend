"""The caller's own opt-in notification settings.

Every route acts on the logged-in user's record only; the user id never comes from the request.
"""

import threading
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_active_user
from app.config import get_settings
from app.db import get_db
from app.models import UserNotificationSettings
from app.models.user import User
from app.notifications import (
    Notification,
    NotificationChannel,
    deliver,
    get_notification_channel,
    new_topic,
)
from app.schemas.notifications import (
    NotificationEvent,
    NotificationSettings,
    NotificationSettingsUpdate,
)

router = APIRouter(
    prefix="/notification-settings",
    tags=["notification-settings"],
    dependencies=[Depends(current_active_user)],
)

TEST_NOTIFICATION_MIN_INTERVAL_S = 10.0

_last_test_sent: dict[int, float] = {}
_last_test_sent_lock = threading.Lock()


def _claim_test_slot(user_id: int) -> float:
    """Seconds the caller still has to wait; 0 when it may send now (and the slot is taken)."""
    now = time.monotonic()
    with _last_test_sent_lock:
        wait = _last_test_sent.get(user_id, -TEST_NOTIFICATION_MIN_INTERVAL_S) + (
            TEST_NOTIFICATION_MIN_INTERVAL_S - now
        )
        if wait > 0:
            return wait
        _last_test_sent[user_id] = now
        return 0.0


def _get_or_create(db: Session, user_id: int) -> UserNotificationSettings:
    row = db.get(UserNotificationSettings, user_id)
    if row is not None:
        return row
    row = UserNotificationSettings(user_id=user_id, enabled=False, topic=new_topic(), events=[])
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent first request created it; use that row so the topic stays single.
        db.rollback()
        row = db.get(UserNotificationSettings, user_id)
        if row is None:
            raise
    return row


def _to_response(row: UserNotificationSettings) -> NotificationSettings:
    return NotificationSettings(
        enabled=row.enabled,
        events=[NotificationEvent(event) for event in row.events],
        topic=row.topic,
        server_url=get_settings().ntfy_base_url,
    )


@router.get("", response_model=NotificationSettings, summary="Get my notification settings",
    description=(
        "Returns `{enabled, events, topic, server_url}` of the calling user and creates the "
        "record, with a fresh topic, on first use. Notifications are opt-in: nobody receives "
        "any until they enable them. Install the ntfy app and subscribe to `topic` on the "
        "server named in `server_url`; the topic can be subscribed to from several devices and "
        "persists across logins and while notifications are disabled. Every endpoint acts on "
        "the caller's own record only and returns 401 without a valid token."
    ),
)
def get_notification_settings(
    db: Session = Depends(get_db), user: User = Depends(current_active_user)
) -> NotificationSettings:
    return _to_response(_get_or_create(db, user.id))


@router.put(
    "",
    response_model=NotificationSettings,
    summary="Update my notification settings",
    description=(
        "Body `{enabled: bool, events: [key, ...]}`. The event keys are `box_started` (a "
        "heartbeat arrives after more than 3 heartbeat intervals of silence), "
        "`measurement_started` (`run_phase` becomes `active_measuring`), `measurement_finished` "
        "(`run_phase` leaves `active_measuring`), `runs_uploaded` (a measurement upload is "
        "stored) and `error` (`run_phase` becomes `critical_error`, `pipeline_broken` turns "
        "`true`, or a command acknowledgement reports `failed`). Events apply to all devices "
        "and only transitions notify. A message holds the device id, the event and the time as "
        "a fixed English text; it never carries error details, config values or "
        "device-supplied strings. Unknown event keys, extra fields (including `topic`) or a "
        "non-boolean `enabled` give 422; duplicate events are removed. Never changes the "
        "topic."
    ),
)
def update_notification_settings(
    update: NotificationSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_active_user),
) -> NotificationSettings:
    row = _get_or_create(db, user.id)
    row.enabled = update.enabled
    row.events = [event.value for event in update.events]
    db.commit()
    return _to_response(row)


@router.post(
    "/regenerate-topic",
    response_model=NotificationSettings,
    summary="Replace my ntfy topic; the old one stops receiving notifications",
    description=(
        "Issues a new topic and returns the settings. The old topic is no longer served, so "
        "subscribe to the new one in the ntfy app. Use it if the topic has become known to "
        "someone else: on the public ntfy.sh instance the topic is the only access control, "
        "and anyone who knows it can read the notifications."
    ),
)
def regenerate_topic(
    db: Session = Depends(get_db), user: User = Depends(current_active_user)
) -> NotificationSettings:
    row = _get_or_create(db, user.id)
    row.topic = new_topic()
    db.commit()
    return _to_response(row)


@router.post(
    "/test",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a test notification to my topic",
    description=(
        "Queues a test notification for the caller's topic and answers 202 without a body. "
        "Called again within 10 seconds it answers 429 with a `Retry-After` header. Delivery "
        "runs after the response, is best effort, times out after 5 seconds and is not "
        "retried. The ntfy server comes from the deployment's configuration and cannot be set "
        "per request; device ids and operating state are sent to that server, so sensitive "
        "deployments should use a self-hosted ntfy instance with access control."
    ),
)
def send_test_notification(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_active_user),
    channel: NotificationChannel = Depends(get_notification_channel),
) -> None:
    wait = _claim_test_slot(user.id)
    if wait > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Test notification was sent too recently",
            headers={"Retry-After": str(int(wait) + 1)},
        )
    row = _get_or_create(db, user.id)
    notification = Notification(title="5GM", message="Test notification")
    background_tasks.add_task(deliver, channel, [([row.topic], notification)])
