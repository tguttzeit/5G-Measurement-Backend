"""In-memory fan-out of "a new heartbeat arrived" signals to SSE subscribers.

Single-process only: the backend runs one uvicorn process, so a per-process registry is enough.
Revisit this registry if the backend ever runs more than one process.

Everything here must be called from the event loop thread (the `async def` endpoints do),
because `asyncio.Queue` is not thread-safe.
"""
import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

MAX_STREAMS_PER_USER = 5
MAX_STREAMS_TOTAL = 100


class StreamLimitExceeded(Exception):
    """Raised by `subscribe` when a per-user or global stream cap is reached."""


@dataclass(frozen=True)
class HeartbeatEvent:
    """A signal only: the heartbeat payload itself is never pushed, clients re-fetch it."""

    device_id: str
    received_at: datetime

    def to_sse(self) -> str:
        data = json.dumps(
            {"device_id": self.device_id, "received_at": self.received_at.isoformat()}
        )
        return f"event: heartbeat\ndata: {data}\n\n"


class Subscription:
    def __init__(self, broadcaster: "HeartbeatBroadcaster", device_id: str, user_id: int):
        self._broadcaster = broadcaster
        self.device_id = device_id
        self.user_id = user_id
        # Only "something changed" matters, so a single pending event is enough (see publish).
        self.queue: asyncio.Queue[HeartbeatEvent] = asyncio.Queue(maxsize=1)
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._broadcaster._remove(self)


class HeartbeatBroadcaster:
    def __init__(
        self, max_per_user: int = MAX_STREAMS_PER_USER, max_total: int = MAX_STREAMS_TOTAL
    ):
        self._max_per_user = max_per_user
        self._max_total = max_total
        self._by_device: defaultdict[str, set[Subscription]] = defaultdict(set)
        self._per_user: defaultdict[int, int] = defaultdict(int)
        self._total = 0

    @property
    def total_subscribers(self) -> int:
        return self._total

    def subscribe(self, device_id: str, user_id: int) -> Subscription:
        """Register a subscriber; the caller must `close()` it when the stream ends."""
        if self._total >= self._max_total or self._per_user.get(user_id, 0) >= self._max_per_user:
            raise StreamLimitExceeded
        subscription = Subscription(self, device_id, user_id)
        self._by_device[device_id].add(subscription)
        self._per_user[user_id] += 1
        self._total += 1
        return subscription

    def publish(self, device_id: str, received_at: datetime) -> None:
        event = HeartbeatEvent(device_id=device_id, received_at=received_at)
        for subscription in self._by_device.get(device_id, ()):
            queue = subscription.queue
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def _remove(self, subscription: Subscription) -> None:
        subscribers = self._by_device[subscription.device_id]
        subscribers.discard(subscription)
        if not subscribers:
            del self._by_device[subscription.device_id]
        self._per_user[subscription.user_id] -= 1
        if self._per_user[subscription.user_id] == 0:
            del self._per_user[subscription.user_id]
        self._total -= 1


heartbeat_broadcaster = HeartbeatBroadcaster()
