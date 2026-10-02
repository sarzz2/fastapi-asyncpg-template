from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from api.apps.common.constants import NotificationChannels
from api.apps.notification.v0.channels.base import BaseNotificationChannel
from api.apps.notification.v0.schemas import NotificationSchema
from api.apps.notification.v0.service import NotificationService, get_notification_service

# pylint: disable=redefined-outer-name


class MockChannel(BaseNotificationChannel):
    """Mock notification channel for testing."""

    async def send(self, user_id: Any, notification: Any) -> None:
        pass

    async def broadcast(self, notification: Any) -> None:
        pass


@pytest.fixture
def notification_service() -> NotificationService:
    """Fixture for NotificationService."""
    mock_dao = MagicMock()
    service = NotificationService(device_dao=mock_dao)
    # Clear default channels for clean testing
    service.channels = {}
    return service


@pytest.mark.asyncio
async def test_register_channel(notification_service: NotificationService) -> None:  # pylint: disable=redefined-outer-name
    """Test registering a channel."""
    channel = MockChannel()
    notification_service.register_channel("mock", channel)
    assert "mock" in notification_service.channels

    # Test duplicate registration
    notification_service.register_channel("mock", channel)
    assert len(notification_service.channels) == 1


@pytest.mark.asyncio
async def test_notify(notification_service: NotificationService) -> None:  # pylint: disable=redefined-outer-name
    """Test sending a notification to a specific user."""
    channel = AsyncMock(spec=BaseNotificationChannel)
    notification_service.register_channel("mock", channel)

    user_id = uuid4()
    message = "Test Message"

    await notification_service.notify(user_id, message)

    channel.send.assert_awaited_once()
    call_args = channel.send.await_args
    assert call_args[0][0] == user_id
    assert isinstance(call_args[0][1], NotificationSchema)
    assert call_args[0][1].message == message


@pytest.mark.asyncio
async def test_notify_with_specific_channels(notification_service: NotificationService) -> None:
    """Test sending only to specified channels and skipping omitted ones."""
    ch1 = AsyncMock(spec=BaseNotificationChannel)
    ch2 = AsyncMock(spec=BaseNotificationChannel)
    notification_service.register_channel(NotificationChannels.EMAIL.value, ch1)
    notification_service.register_channel(NotificationChannels.SSE.value, ch2)

    user_id = uuid4()
    await notification_service.notify(user_id, "Only Email", channels=[NotificationChannels.EMAIL])

    ch1.send.assert_awaited_once()
    ch2.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_broadcast_all(notification_service: NotificationService) -> None:  # pylint: disable=redefined-outer-name
    """Test broadcasting a message to all users."""
    channel = AsyncMock(spec=BaseNotificationChannel)
    notification_service.register_channel("mock", channel)

    message = "Broadcast"

    await notification_service.broadcast_all(message)

    channel.broadcast.assert_awaited_once()
    call_args = channel.broadcast.await_args
    assert isinstance(call_args[0][0], NotificationSchema)
    assert call_args[0][0].message == message


@pytest.mark.asyncio
async def test_broadcast_all_with_specific_channels(notification_service: NotificationService) -> None:
    """Test broadcasting only to specified channels."""
    ch1 = AsyncMock(spec=BaseNotificationChannel)
    ch2 = AsyncMock(spec=BaseNotificationChannel)
    notification_service.register_channel(NotificationChannels.EMAIL.value, ch1)
    notification_service.register_channel(NotificationChannels.FCM.value, ch2)

    await notification_service.broadcast_all("Only FCM", channels=[NotificationChannels.FCM])

    ch1.broadcast.assert_not_awaited()
    ch2.broadcast.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_sse(notification_service: NotificationService) -> None:  # pylint: disable=redefined-outer-name
    """Test SSE generator yields messages and handles disconnect."""
    mock_request = AsyncMock()
    mock_request.is_disconnected.side_effect = [False, True]

    user_id = uuid4()
    mock_pubsub = AsyncMock()
    mock_pubsub.get_message.return_value = {
        "type": "message",
        "data": '{"message": "hello"}',
    }

    with patch("api.apps.notification.v0.service.redis_socket") as mock_socket:
        mock_socket.client.pubsub.return_value = mock_pubsub
        events = []
        async for event in notification_service.stream_sse(mock_request, user_id):
            events.append(event)

        assert len(events) == 1
        assert "event: notification" in events[0]
        assert 'data: {"message": "hello"}' in events[0]
        mock_pubsub.subscribe.assert_awaited_once()
        mock_pubsub.unsubscribe.assert_awaited_once()
        mock_pubsub.aclose.assert_awaited_once()


def test_get_notification_service() -> None:
    """Test dependency injection getter."""
    mock_dao = MagicMock()
    service = get_notification_service(device_dao=mock_dao)
    assert isinstance(service, NotificationService)
