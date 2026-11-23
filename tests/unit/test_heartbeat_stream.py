"""Tests for GET /heartbeat/stream that need no database.

The endpoint's device lookup is stubbed via a `get_db` override. Round-trip coverage against a
real device row and a real heartbeat POST lives in the integration suite
(tests/integration/test_api/test_heartbeat_stream.py).
A live SSE response is infinite, so the event loop itself is exercised through the generator
(`event_stream`) rather than through TestClient.
"""
import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import current_active_user
from app.db import get_db
from app.heartbeat_events import HeartbeatBroadcaster
from app.main import app
from app.routers import heartbeat as heartbeat_router
from app.routers.heartbeat import event_stream

STREAM_URL = "/heartbeat/stream"
RECEIVED_AT = datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC)


class _FakeDb:
    def __init__(self, known_device_ids: set[str]):
        self._known = known_device_ids

    def get(self, model, device_id):
        return SimpleNamespace(device_id=device_id) if device_id in self._known else None


@pytest.fixture
def authenticated_client(monkeypatch):
    broadcaster = HeartbeatBroadcaster(max_per_user=1)
    monkeypatch.setattr(heartbeat_router, "heartbeat_broadcaster", broadcaster)
    app.dependency_overrides[current_active_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[get_db] = lambda: _FakeDb({"device-01"})
    yield TestClient(app), broadcaster
    app.dependency_overrides.clear()


def test_stream_requires_authentication():
    response = TestClient(app).get(STREAM_URL, params={"device_id": "device-01"})

    assert response.status_code == 401


def test_stream_requires_device_id():
    app.dependency_overrides[current_active_user] = lambda: SimpleNamespace(id=1)
    try:
        response = TestClient(app).get(STREAM_URL)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_stream_unknown_device_is_404(authenticated_client):
    client, broadcaster = authenticated_client

    response = client.get(STREAM_URL, params={"device_id": "no-such-device"})

    assert response.status_code == 404
    assert "no-such-device" not in response.text
    assert broadcaster.total_subscribers == 0


def test_stream_over_the_per_user_cap_is_429(authenticated_client):
    client, broadcaster = authenticated_client
    broadcaster.subscribe("device-01", user_id=1)

    response = client.get(STREAM_URL, params={"device_id": "device-01"})

    assert response.status_code == 429


def test_event_stream_sends_connected_comment_first():
    async def scenario():
        broadcaster = HeartbeatBroadcaster()
        subscription = broadcaster.subscribe("device-01", user_id=1)
        stream = event_stream(subscription, keepalive_s=60)

        assert await anext(stream) == ": connected\n\n"
        await stream.aclose()

    asyncio.run(scenario())


def test_event_stream_emits_published_heartbeat_as_signal_only():
    async def scenario():
        broadcaster = HeartbeatBroadcaster()
        subscription = broadcaster.subscribe("device-01", user_id=1)
        stream = event_stream(subscription, keepalive_s=60)
        await anext(stream)

        broadcaster.publish("device-01", RECEIVED_AT)

        assert await anext(stream) == (
            'event: heartbeat\n'
            'data: {"device_id": "device-01", "received_at": "2026-01-01T00:00:30+00:00"}\n\n'
        )
        await stream.aclose()

    asyncio.run(scenario())


def test_event_stream_sends_keepalive_comment_when_idle():
    async def scenario():
        broadcaster = HeartbeatBroadcaster()
        subscription = broadcaster.subscribe("device-01", user_id=1)
        stream = event_stream(subscription, keepalive_s=0.01)
        await anext(stream)

        assert await anext(stream) == ": keep-alive\n\n"
        await stream.aclose()

    asyncio.run(scenario())


def test_event_stream_unsubscribes_when_closed():
    async def scenario():
        broadcaster = HeartbeatBroadcaster()
        subscription = broadcaster.subscribe("device-01", user_id=1)
        stream = event_stream(subscription, keepalive_s=60)
        await anext(stream)

        await stream.aclose()

        assert broadcaster.total_subscribers == 0

    asyncio.run(scenario())


def test_event_stream_unsubscribes_when_cancelled_while_waiting():
    async def scenario():
        broadcaster = HeartbeatBroadcaster()
        subscription = broadcaster.subscribe("device-01", user_id=1)
        stream = event_stream(subscription, keepalive_s=60)
        await anext(stream)

        waiting = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

        assert broadcaster.total_subscribers == 0

    asyncio.run(scenario())
