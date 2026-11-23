"""In-memory fan-out of "a device uploaded measurements" signals to SSE subscribers.

Single-process only, same constraint as app/heartbeat_events.py: revisit
this if the backend ever runs more than one process.

Unlike heartbeat events, subscribers are not scoped to one device: a dashboard user triggers
`force-upload-now` without knowing in advance which device's upload will land first, so every
subscription hears about every device's uploads. Events also carry real content (the run ids just
uploaded), not just a "something changed" signal, so losing one silently would mean the dashboard
never tells the user what was uploaded - the per-subscriber queue is bounded but drops the oldest
pending event rather than the newest.

Everything here must be called from the event loop thread (the `async def` endpoints do), because
`asyncio.Queue` is not thread-safe.
"""
import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

MAX_STREAMS_PER_USER = 5
MAX_STREAMS_TOTAL = 100

# Generous relative to how often one device uploads; only matters if a client stops reading
# frames (e.g. a backgrounded tab) for a long stretch while several devices upload concurrently.
MAX_QUEUED_EVENTS_PER_SUBSCRIBER = 16


class StreamLimitExceeded(Exception):
    """Raised by `subscribe` when a per-user or global stream cap is reached."""


@dataclass(frozen=True)
class UploadEvent:
    device_id: str
    run_ids: list[str]
    point_count: int
    received_at: datetime

    def to_sse(self) -> str:
        data = json.dumps(
            {
                "device_id": self.device_id,
                "run_ids": self.run_ids,
                "point_count": self.point_count,
                "received_at": self.received_at.isoformat(),
            }
        )
        return f"event: upload\ndata: {data}\n\n"


class Subscription:
    def __init__(self, broadcaster: "UploadBroadcaster", user_id: int):
        self._broadcaster = broadcaster
        self.user_id = user_id
        self.queue: asyncio.Queue[UploadEvent] = asyncio.Queue(
            maxsize=MAX_QUEUED_EVENTS_PER_SUBSCRIBER
        )
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._broadcaster._remove(self)


class UploadBroadcaster:
    def __init__(
        self, max_per_user: int = MAX_STREAMS_PER_USER, max_total: int = MAX_STREAMS_TOTAL
    ):
        self._max_per_user = max_per_user
        self._max_total = max_total
        self._subscriptions: set[Subscription] = set()
        self._per_user: defaultdict[int, int] = defaultdict(int)
        self._total = 0

    @property
    def total_subscribers(self) -> int:
        return self._total

    def subscribe(self, user_id: int) -> Subscription:
        """Register a subscriber; the caller must `close()` it when the stream ends."""
        if self._total >= self._max_total or self._per_user.get(user_id, 0) >= self._max_per_user:
            raise StreamLimitExceeded
        subscription = Subscription(self, user_id)
        self._subscriptions.add(subscription)
        self._per_user[user_id] += 1
        self._total += 1
        return subscription

    def publish(
        self, device_id: str, run_ids: list[str], point_count: int, received_at: datetime
    ) -> None:
        event = UploadEvent(
            device_id=device_id, run_ids=run_ids, point_count=point_count, received_at=received_at
        )
        for subscription in self._subscriptions:
            queue = subscription.queue
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def _remove(self, subscription: Subscription) -> None:
        self._subscriptions.discard(subscription)
        self._per_user[subscription.user_id] -= 1
        if self._per_user[subscription.user_id] == 0:
            del self._per_user[subscription.user_id]
        self._total -= 1


upload_broadcaster = UploadBroadcaster()
