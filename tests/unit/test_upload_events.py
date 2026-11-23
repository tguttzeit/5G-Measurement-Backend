"""Unit tests for the in-memory upload broadcaster."""
import asyncio
from datetime import UTC, datetime

import pytest

from app.upload_events import (
    MAX_QUEUED_EVENTS_PER_SUBSCRIBER,
    StreamLimitExceeded,
    UploadBroadcaster,
    UploadEvent,
)

RECEIVED_AT = datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC)


def _event(
    device_id: str = "device-01", run_ids: list[str] | None = None, point_count: int = 3
) -> UploadEvent:
    return UploadEvent(
        device_id=device_id,
        run_ids=run_ids if run_ids is not None else ["run-01"],
        point_count=point_count,
        received_at=RECEIVED_AT,
    )


def test_publish_reaches_every_subscriber_regardless_of_device():
    async def scenario():
        broadcaster = UploadBroadcaster()
        first = broadcaster.subscribe(user_id=1)
        second = broadcaster.subscribe(user_id=2)

        broadcaster.publish("device-01", ["run-01"], 3, RECEIVED_AT)

        assert first.queue.get_nowait() == _event()
        assert second.queue.get_nowait() == _event()

    asyncio.run(scenario())


def test_publish_without_subscribers_is_a_no_op():
    async def scenario():
        UploadBroadcaster().publish("device-01", ["run-01"], 3, RECEIVED_AT)

    asyncio.run(scenario())


def test_full_queue_drops_the_oldest_event_not_the_newest():
    async def scenario():
        broadcaster = UploadBroadcaster()
        subscription = broadcaster.subscribe(user_id=1)

        for i in range(MAX_QUEUED_EVENTS_PER_SUBSCRIBER + 1):
            broadcaster.publish(f"device-{i:02d}", [f"run-{i:02d}"], 1, RECEIVED_AT)

        assert subscription.queue.qsize() == MAX_QUEUED_EVENTS_PER_SUBSCRIBER
        first_remaining = subscription.queue.get_nowait()
        assert first_remaining.device_id == "device-01"  # device-00 was the one dropped

    asyncio.run(scenario())


def test_close_unsubscribes_and_is_idempotent():
    async def scenario():
        broadcaster = UploadBroadcaster()
        subscription = broadcaster.subscribe(user_id=1)

        subscription.close()
        subscription.close()
        broadcaster.publish("device-01", ["run-01"], 3, RECEIVED_AT)

        assert subscription.queue.empty()
        assert broadcaster.total_subscribers == 0

    asyncio.run(scenario())


def test_close_releases_the_per_user_slot():
    async def scenario():
        broadcaster = UploadBroadcaster(max_per_user=1)
        subscription = broadcaster.subscribe(user_id=1)
        subscription.close()

        broadcaster.subscribe(user_id=1).close()

    asyncio.run(scenario())


def test_per_user_cap_rejects_additional_streams():
    async def scenario():
        broadcaster = UploadBroadcaster(max_per_user=2)
        broadcaster.subscribe(user_id=1)
        broadcaster.subscribe(user_id=1)

        with pytest.raises(StreamLimitExceeded):
            broadcaster.subscribe(user_id=1)

        broadcaster.subscribe(user_id=2)

    asyncio.run(scenario())


def test_total_cap_rejects_additional_streams():
    async def scenario():
        broadcaster = UploadBroadcaster(max_per_user=5, max_total=2)
        broadcaster.subscribe(user_id=1)
        broadcaster.subscribe(user_id=2)

        with pytest.raises(StreamLimitExceeded):
            broadcaster.subscribe(user_id=3)

    asyncio.run(scenario())


def test_rejected_subscribe_does_not_leak_a_slot():
    async def scenario():
        broadcaster = UploadBroadcaster(max_per_user=1)
        broadcaster.subscribe(user_id=1)

        with pytest.raises(StreamLimitExceeded):
            broadcaster.subscribe(user_id=1)

        assert broadcaster.total_subscribers == 1

    asyncio.run(scenario())


def test_event_serializes_device_id_run_ids_and_point_count():
    assert _event().to_sse() == (
        "event: upload\n"
        'data: {"device_id": "device-01", "run_ids": ["run-01"], "point_count": 3, '
        '"received_at": "2026-01-01T00:00:30+00:00"}\n\n'
    )
