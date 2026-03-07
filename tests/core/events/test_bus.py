from unittest.mock import AsyncMock, patch

import pytest

from api.core.events.bus import EventBus
from api.core.events.schema import ApplicationEvent


class DummyEvent(ApplicationEvent):
    """Dummy event for testing purposes."""

    event_name: str = "dummy.event"


def test_event_bus_subscription() -> None:
    """Test event bus subscription."""
    bus = EventBus()
    handled_events = []

    def dummy_handler(event: ApplicationEvent) -> None:
        handled_events.append(event)

    bus.subscribe("dummy.event", dummy_handler)
    assert len(bus._subscribers["dummy.event"]) == 1  # pylint: disable=protected-access


@pytest.mark.asyncio
@patch("api.core.events.bus.redis_client.client")
async def test_event_bus_publish(mock_redis_client: AsyncMock) -> None:
    """Test event bus publish."""
    bus = EventBus()
    event = DummyEvent(payload={"test": "ok"})

    mock_redis_client.publish = AsyncMock()
    await bus.publish(event)

    mock_redis_client.publish.assert_called_once_with("event_bus:broadcast", event.model_dump_json())


@pytest.mark.asyncio
@patch("api.core.events.bus.redis_client.client")
async def test_process_remote_event(mock_redis_client: AsyncMock) -> None:
    """Test processing a remote event from Redis with locking."""
    bus = EventBus()
    handled_events = []

    def dummy_handler(event: ApplicationEvent) -> None:
        handled_events.append(event)

    bus.subscribe("dummy.event", dummy_handler)

    event = DummyEvent(payload={"test": "ok"})
    mock_redis_client.set = AsyncMock(return_value=True)

    await bus._process_remote_event(event.model_dump_json())  # pylint: disable=protected-access

    assert len(handled_events) == 1
    assert handled_events[0].payload == {"test": "ok"}
    mock_redis_client.set.assert_called_once_with(f"event_bus:lock:{event.event_id}", "1", nx=True, ex=60)


@pytest.mark.asyncio
@patch("api.core.events.bus.redis_client.client")
async def test_process_remote_event_lock_failed(mock_redis_client: AsyncMock) -> None:
    """Test processing a remote event from Redis when lock is already held."""
    bus = EventBus()
    handled_events = []

    def dummy_handler(event: ApplicationEvent) -> None:
        handled_events.append(event)

    bus.subscribe("dummy.event", dummy_handler)

    event = DummyEvent(payload={"test": "ok"})
    mock_redis_client.set = AsyncMock(return_value=False)

    await bus._process_remote_event(event.model_dump_json())  # pylint: disable=protected-access

    assert len(handled_events) == 0
    mock_redis_client.set.assert_called_once_with(f"event_bus:lock:{event.event_id}", "1", nx=True, ex=60)
