from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from api.apps.notification.schemas import NotificationSchema
from api.apps.notification.v0.channels.base import BaseNotificationChannel
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
    service = NotificationService()
    # Clear default channels for clean testing
    service.channels = []
    return service


@pytest.mark.asyncio
async def test_register_channel(notification_service: NotificationService) -> None:  # pylint: disable=redefined-outer-name
    """Test registering a channel."""
    channel = MockChannel()
    notification_service.register_channel(channel)
    assert channel in notification_service.channels

    # Test duplicate registration
    notification_service.register_channel(channel)
    assert len(notification_service.channels) == 1


@pytest.mark.asyncio
async def test_notify(notification_service: NotificationService) -> None:  # pylint: disable=redefined-outer-name
    """Test sending a notification to a specific user."""
    channel = AsyncMock(spec=BaseNotificationChannel)
    notification_service.register_channel(channel)

    user_id = uuid4()
    message = "Test Message"

    await notification_service.notify(user_id, message)

    channel.send.assert_awaited_once()
    call_args = channel.send.await_args
    assert call_args[0][0] == user_id
    assert isinstance(call_args[0][1], NotificationSchema)
    assert call_args[0][1].message == message


@pytest.mark.asyncio
async def test_broadcast_all(notification_service: NotificationService) -> None:  # pylint: disable=redefined-outer-name
    """Test broadcasting a message to all users."""
    channel = AsyncMock(spec=BaseNotificationChannel)
    notification_service.register_channel(channel)

    message = "Broadcast"

    await notification_service.broadcast_all(message)

    channel.broadcast.assert_awaited_once()
    call_args = channel.broadcast.await_args
    assert isinstance(call_args[0][0], NotificationSchema)
    assert call_args[0][0].message == message


def test_get_notification_service() -> None:
    """Test dependency injection getter."""
    service = get_notification_service()
    assert isinstance(service, NotificationService)
