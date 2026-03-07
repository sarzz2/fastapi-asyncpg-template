from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.core.events.bus import EventBus
from api.core.events.schema import ApplicationEvent


class DummyEvent(ApplicationEvent):
    """
    Represent a minimal event for unit testing.
    """

    event_name: str = "dummy.event"


@pytest.fixture
def mock_redis_client() -> Generator[MagicMock, None, None]:
    """
    Provide a pre-configured mock Redis client for EventBus tests.
    Ensures that pubsub() returns a mock object and not a coroutine.
    """
    with patch("api.core.events.bus.redis_event_bus.client") as mock_client:
        mock_client.pubsub = MagicMock()
        mock_pubsub = AsyncMock()
        mock_client.pubsub.return_value = mock_pubsub
        mock_client.publish = AsyncMock()
        mock_client.set = AsyncMock()
        yield mock_client


def test_event_bus_subscription() -> None:
    """
    Verify that handlers can successfully subscribe to specific event names.
    """
    bus = EventBus()
    handled_events = []

    def dummy_handler(event: ApplicationEvent) -> None:
        handled_events.append(event)

    bus.subscribe("dummy.event", dummy_handler)

    # Internal state check is acceptable for unit testing the subscription logic
    assert len(bus._subscribers["dummy.event"]) == 1  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_event_bus_publish(mock_redis_client: MagicMock) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that publishing an event correctly sends it to the Redis broadcast channel.
    """
    bus = EventBus()
    event = DummyEvent(payload={"data": "test_payload"})

    try:
        await bus.publish(event)

        mock_redis_client.publish.assert_called_once_with("event_bus:broadcast", event.model_dump_json())
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_process_remote_event_with_lock_success(mock_redis_client: MagicMock) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that a remote event is processed only if the idempotent lock is successfully acquired.
    """
    bus = EventBus()
    received_events = []

    def dummy_handler(event: ApplicationEvent) -> None:
        received_events.append(event)

    bus.subscribe("dummy.event", dummy_handler)
    event = DummyEvent(payload={"data": "remote_data"})

    # Simulate successful lock acquisition
    mock_redis_client.set.return_value = True

    try:
        await bus._process_remote_event(event.model_dump_json())  # pylint: disable=protected-access

        assert len(received_events) == 1
        assert received_events[0].payload == {"data": "remote_data"}

        lock_key = f"event_bus:lock:{event.event_id}"
        mock_redis_client.set.assert_called_once_with(lock_key, "1", nx=True, ex=60)
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_process_remote_event_lock_already_held(mock_redis_client: MagicMock) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that a remote event is ignored if the idempotent lock is already held by another process.
    """
    bus = EventBus()
    received_events = []

    def dummy_handler(event: ApplicationEvent) -> None:
        received_events.append(event)

    bus.subscribe("dummy.event", dummy_handler)
    event = DummyEvent(payload={"data": "skipped_data"})

    # Simulate lock acquisition failure
    mock_redis_client.set.return_value = False

    try:
        await bus._process_remote_event(event.model_dump_json())  # pylint: disable=protected-access

        # Handler should NOT have been called
        assert len(received_events) == 0
        mock_redis_client.set.assert_called_once()
    finally:
        await bus.stop()
