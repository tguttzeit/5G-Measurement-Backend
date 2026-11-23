"""Unit tests for the in-memory command-ack broadcaster."""
import asyncio
from datetime import UTC, datetime

import pytest

from app.command_events import (
    MAX_QUEUED_EVENTS_PER_SUBSCRIBER,
    CommandAckBroadcaster,
    CommandAckEvent,
    StreamLimitExceeded,
)

RECEIVED_AT = datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC)


def _event(
    device_id: str = "device-01",
    command_id: int = 1,
    command: str = "reboot-now",
    status: str = "received",
    error: str | None = None,
) -> CommandAckEvent:
    return CommandAckEvent(
        device_id=device_id,
        command_id=command_id,
        command=command,
        status=status,
        error=error,
        received_at=RECEIVED_AT,
    )


def test_publish_reaches_every_subscriber_regardless_of_device():
    async def scenario():
        broadcaster = CommandAckBroadcaster()
        first = broadcaster.subscribe(user_id=1)
        second = broadcaster.subscribe(user_id=2)

        broadcaster.publish("device-01", 1, "reboot-now", "received", None, RECEIVED_AT)

        assert first.queue.get_nowait() == _event()
        assert second.queue.get_nowait() == _event()

    asyncio.run(scenario())


def test_publish_without_subscribers_is_a_no_op():
    async def scenario():
        CommandAckBroadcaster().publish("device-01", 1, "reboot-now", "received", None, RECEIVED_AT)

    asyncio.run(scenario())


def test_full_queue_drops_the_oldest_event_not_the_newest():
    async def scenario():
        broadcaster = CommandAckBroadcaster()
        subscription = broadcaster.subscribe(user_id=1)

        for i in range(MAX_QUEUED_EVENTS_PER_SUBSCRIBER + 1):
            broadcaster.publish(f"device-{i:02d}", i, "reboot-now", "received", None, RECEIVED_AT)

        assert subscription.queue.qsize() == MAX_QUEUED_EVENTS_PER_SUBSCRIBER
        first_remaining = subscription.queue.get_nowait()
        assert first_remaining.device_id == "device-01"  # device-00 was the one dropped

    asyncio.run(scenario())


def test_close_unsubscribes_and_is_idempotent():
    async def scenario():
        broadcaster = CommandAckBroadcaster()
        subscription = broadcaster.subscribe(user_id=1)

        subscription.close()
        subscription.close()
        broadcaster.publish("device-01", 1, "reboot-now", "received", None, RECEIVED_AT)

        assert subscription.queue.empty()
        assert broadcaster.total_subscribers == 0

    asyncio.run(scenario())


def test_close_releases_the_per_user_slot():
    async def scenario():
        broadcaster = CommandAckBroadcaster(max_per_user=1)
        subscription = broadcaster.subscribe(user_id=1)
        subscription.close()

        broadcaster.subscribe(user_id=1).close()

    asyncio.run(scenario())


def test_per_user_cap_rejects_additional_streams():
    async def scenario():
        broadcaster = CommandAckBroadcaster(max_per_user=2)
        broadcaster.subscribe(user_id=1)
        broadcaster.subscribe(user_id=1)

        with pytest.raises(StreamLimitExceeded):
            broadcaster.subscribe(user_id=1)

        broadcaster.subscribe(user_id=2)

    asyncio.run(scenario())


def test_total_cap_rejects_additional_streams():
    async def scenario():
        broadcaster = CommandAckBroadcaster(max_per_user=5, max_total=2)
        broadcaster.subscribe(user_id=1)
        broadcaster.subscribe(user_id=2)

        with pytest.raises(StreamLimitExceeded):
            broadcaster.subscribe(user_id=3)

    asyncio.run(scenario())


def test_event_serializes_every_field():
    assert _event(error=None).to_sse() == (
        "event: command_ack\n"
        'data: {"device_id": "device-01", "command_id": 1, "command": "reboot-now", '
        '"status": "received", "error": null, "received_at": "2026-01-01T00:00:30+00:00"}\n\n'
    )


def test_event_serializes_an_error_message():
    event = _event(command="fan-override-now", status="failed", error="Fan control is disabled")
    assert '"error": "Fan control is disabled"' in event.to_sse()
