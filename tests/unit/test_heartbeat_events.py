"""Unit tests for the in-memory heartbeat broadcaster."""
import asyncio
import json
from datetime import UTC, datetime

import pytest

from app.heartbeat_events import (
    HeartbeatBroadcaster,
    HeartbeatEvent,
    StreamLimitExceeded,
)

RECEIVED_AT = datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC)


def _event(device_id: str = "device-01") -> HeartbeatEvent:
    return HeartbeatEvent(device_id=device_id, received_at=RECEIVED_AT)


def test_publish_reaches_subscriber_of_that_device():
    async def scenario():
        broadcaster = HeartbeatBroadcaster()
        subscription = broadcaster.subscribe("device-01", user_id=1)

        broadcaster.publish("device-01", RECEIVED_AT)

        assert subscription.queue.get_nowait() == _event()
        subscription.close()

    asyncio.run(scenario())


def test_publish_is_filtered_per_device():
    async def scenario():
        broadcaster = HeartbeatBroadcaster()
        other = broadcaster.subscribe("device-02", user_id=1)

        broadcaster.publish("device-01", RECEIVED_AT)

        assert other.queue.empty()
        other.close()

    asyncio.run(scenario())


def test_publish_reaches_every_subscriber_of_the_device():
    async def scenario():
        broadcaster = HeartbeatBroadcaster()
        first = broadcaster.subscribe("device-01", user_id=1)
        second = broadcaster.subscribe("device-01", user_id=2)

        broadcaster.publish("device-01", RECEIVED_AT)

        assert first.queue.get_nowait() == _event()
        assert second.queue.get_nowait() == _event()

    asyncio.run(scenario())


def test_publish_without_subscribers_is_a_no_op():
    async def scenario():
        HeartbeatBroadcaster().publish("device-01", RECEIVED_AT)

    asyncio.run(scenario())


def test_unconsumed_events_are_coalesced_to_the_latest():
    async def scenario():
        broadcaster = HeartbeatBroadcaster()
        subscription = broadcaster.subscribe("device-01", user_id=1)
        later = datetime(2026, 1, 1, 0, 1, 30, tzinfo=UTC)

        broadcaster.publish("device-01", RECEIVED_AT)
        broadcaster.publish("device-01", later)

        assert subscription.queue.qsize() == 1
        assert subscription.queue.get_nowait() == HeartbeatEvent("device-01", later)

    asyncio.run(scenario())


def test_close_unsubscribes_and_is_idempotent():
    async def scenario():
        broadcaster = HeartbeatBroadcaster()
        subscription = broadcaster.subscribe("device-01", user_id=1)

        subscription.close()
        subscription.close()
        broadcaster.publish("device-01", RECEIVED_AT)

        assert subscription.queue.empty()
        assert broadcaster.total_subscribers == 0

    asyncio.run(scenario())


def test_close_releases_the_per_user_slot():
    async def scenario():
        broadcaster = HeartbeatBroadcaster(max_per_user=1)
        subscription = broadcaster.subscribe("device-01", user_id=1)
        subscription.close()

        broadcaster.subscribe("device-01", user_id=1).close()

    asyncio.run(scenario())


def test_per_user_cap_rejects_additional_streams():
    async def scenario():
        broadcaster = HeartbeatBroadcaster(max_per_user=2)
        broadcaster.subscribe("device-01", user_id=1)
        broadcaster.subscribe("device-02", user_id=1)

        with pytest.raises(StreamLimitExceeded):
            broadcaster.subscribe("device-01", user_id=1)

        broadcaster.subscribe("device-01", user_id=2)

    asyncio.run(scenario())


def test_total_cap_rejects_additional_streams():
    async def scenario():
        broadcaster = HeartbeatBroadcaster(max_per_user=5, max_total=2)
        broadcaster.subscribe("device-01", user_id=1)
        broadcaster.subscribe("device-01", user_id=2)

        with pytest.raises(StreamLimitExceeded):
            broadcaster.subscribe("device-01", user_id=3)

    asyncio.run(scenario())


def test_rejected_subscribe_does_not_leak_a_slot():
    async def scenario():
        broadcaster = HeartbeatBroadcaster(max_per_user=1)
        broadcaster.subscribe("device-01", user_id=1)

        with pytest.raises(StreamLimitExceeded):
            broadcaster.subscribe("device-01", user_id=1)

        assert broadcaster.total_subscribers == 1

    asyncio.run(scenario())


def test_event_serializes_only_device_id_and_received_at():
    assert _event().to_sse() == (
        'event: heartbeat\n'
        'data: {"device_id": "device-01", "received_at": "2026-01-01T00:00:30+00:00"}\n\n'
    )


def test_sse_event_carries_no_heartbeat_payload():
    event = HeartbeatEvent(device_id="dev-1", received_at=datetime(2026, 10, 30, tzinfo=UTC))

    assert json.loads(event.to_sse().split("data: ")[1]) == {
        "device_id": "dev-1",
        "received_at": "2026-10-30T00:00:00+00:00",
    }
