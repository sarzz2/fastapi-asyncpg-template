# pylint: disable=protected-access, redefined-outer-name
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import WebSocket

from api.apps.notification.schemas import NotificationSchema, NotificationType
from api.apps.notification.v0.channels.websocket import ConnectionManager, WebSocketChannel


@pytest.fixture
def manager() -> ConnectionManager:
    """Create a ConnectionManager instance for testing."""
    return ConnectionManager()


@pytest.fixture
def mock_ws() -> MagicMock:
    """Create a mock WebSocket instance."""
    ws = MagicMock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_manager_connect_disconnect(manager: ConnectionManager, mock_ws: MagicMock) -> None:
    """Test that valid connections are accepted and stored, and removals work."""
    user_id = uuid4()

    # Test connect
    manager._ensure_listener = AsyncMock()  # type: ignore

    await manager.connect(mock_ws, user_id)

    assert user_id in manager.active_connections
    assert mock_ws in manager.active_connections[user_id]
    mock_ws.accept.assert_awaited_once()
    manager._ensure_listener.assert_awaited_once()

    # Test disconnect
    await manager.disconnect(mock_ws, user_id)
    assert user_id not in manager.active_connections


@pytest.mark.asyncio
async def test_manager_local_send_error_handling(manager: ConnectionManager, mock_ws: MagicMock) -> None:
    """Test that connection is removed if send fails."""
    user_id = uuid4()
    manager.active_connections[user_id] = [mock_ws]

    mock_ws.send_text.side_effect = Exception("Connection closed")

    await manager._local_send("test message", user_id)

    # Should be removed from connections
    assert user_id not in manager.active_connections


@pytest.mark.asyncio
async def test_redis_listener_dispatch(manager: ConnectionManager) -> None:
    """Test redis listener dispatches messages correctly."""
    user_id = uuid4()
    manager._local_send = AsyncMock()  # type: ignore
    manager._local_broadcast = AsyncMock()  # type: ignore

    # Mock pubsub
    mock_pubsub = MagicMock()
    manager.pubsub = mock_pubsub

    # Mock messages
    messages = [
        {"type": "message", "channel": "notifications:broadcast", "data": "broadcast_msg"},
        {"type": "message", "channel": f"notifications:user:{user_id}", "data": "user_msg"},
        {"type": "message", "channel": "notifications:user:invalid-uuid", "data": "invalid_msg"},
    ]

    async def mock_listen() -> AsyncGenerator[Any, None]:
        for msg in messages:
            yield msg

    mock_pubsub.listen = mock_listen

    await manager._redis_listener()

    manager._local_broadcast.assert_awaited_with("broadcast_msg")
    manager._local_send.assert_awaited_with("user_msg", user_id)


@pytest.mark.asyncio
async def test_websocket_channel(manager: ConnectionManager) -> None:
    """Test WebSocketChannel delegates send/broadcast to the manager."""
    channel = WebSocketChannel(manager)
    manager.send_personal_message = AsyncMock()  # type: ignore
    manager.broadcast = AsyncMock()  # type: ignore

    user_id = uuid4()
    notification = NotificationSchema(message="test", notification_type=NotificationType.INFO)

    await channel.send(user_id, notification)
    manager.send_personal_message.assert_awaited_once()

    await channel.broadcast(notification)
    manager.broadcast.assert_awaited_once()
