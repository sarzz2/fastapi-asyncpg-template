from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from api.apps.notification.v0.channels.sse import SSEChannel
from api.apps.notification.v0.schemas import NotificationSchema, NotificationType


@pytest.mark.asyncio
async def test_sse_channel_send() -> None:
    """Test SSEChannel.send publishes to user-specific Redis channel."""
    channel = SSEChannel()
    user_id = uuid4()
    notification = NotificationSchema(
        type=NotificationType.INFO,
        message="SSE Personal notification",
        subject="Important",
    )

    with patch("api.apps.notification.v0.channels.sse.redis_socket") as mock_redis_socket:
        mock_redis_socket.client.publish = AsyncMock()
        await channel.send(user_id, notification)

        mock_redis_socket.client.publish.assert_awaited_once_with(
            f"notifications:user:{user_id}",
            notification.model_dump_json(),
        )


@pytest.mark.asyncio
async def test_sse_channel_broadcast() -> None:
    """Test SSEChannel.broadcast publishes to broadcast Redis channel."""
    channel = SSEChannel()
    notification = NotificationSchema(
        type=NotificationType.WARNING,
        message="System broadcast message",
    )

    with patch("api.apps.notification.v0.channels.sse.redis_socket") as mock_redis_socket:
        mock_redis_socket.client.publish = AsyncMock()
        await channel.broadcast(notification)

        mock_redis_socket.client.publish.assert_awaited_once_with(
            "notifications:broadcast",
            notification.model_dump_json(),
        )
