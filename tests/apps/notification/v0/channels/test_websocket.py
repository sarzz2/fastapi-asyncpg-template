from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import WebSocket

from api.apps.notification.v0.channels.websocket import ConnectionManager

# pylint: disable=redefined-outer-name, unused-argument


@pytest.fixture
async def connection_manager(mock_redis_pubsub: Any) -> AsyncGenerator[ConnectionManager, None]:
    """Fixture for ConnectionManager."""
    manager = ConnectionManager()
    yield manager
    await manager.stop()


@pytest.fixture
def mock_websocket() -> AsyncMock:
    """Fixture for WebSocket mock."""
    ws = AsyncMock(spec=WebSocket)
    return ws


@pytest.fixture
def mock_redis_pubsub() -> Any:
    """Fixture for Redis PubSub mock."""
    with patch("api.apps.notification.v0.channels.websocket.redis_socket") as mock_redis:
        mock_pubsub = AsyncMock()

        # pubsub.listen() should return an async iterator
        async def mock_listen_gen() -> AsyncGenerator[dict, None]:
            yield {}

        mock_pubsub.listen = MagicMock(return_value=mock_listen_gen())
        mock_redis.client.pubsub.return_value = mock_pubsub
        mock_redis.client.publish = AsyncMock()
        yield mock_pubsub, mock_redis


@pytest.mark.asyncio
async def test_connect(
    connection_manager: ConnectionManager, mock_websocket: AsyncMock, mock_redis_pubsub: Any
) -> None:  # pylint: disable=redefined-outer-name
    """Test user connection."""
    mock_pubsub, _ = mock_redis_pubsub
    user_id = uuid4()

    await connection_manager.connect(mock_websocket, user_id)

    assert user_id in connection_manager.active_connections
    assert mock_websocket in connection_manager.active_connections[user_id]
    mock_websocket.accept.assert_awaited_once()

    # Verify global broadcast subscription
    mock_pubsub.subscribe.assert_any_await("notifications:broadcast")
    # Verify user channel subscription
    mock_pubsub.subscribe.assert_any_await(f"notifications:user:{user_id}")


@pytest.mark.asyncio
async def test_disconnect_last_connection(
    connection_manager: ConnectionManager, mock_websocket: AsyncMock, mock_redis_pubsub: Any
) -> None:  # pylint: disable=redefined-outer-name
    """Test user disconnection (last connection)."""
    mock_pubsub, _ = mock_redis_pubsub
    user_id = uuid4()

    # Setup initial state
    await connection_manager.connect(mock_websocket, user_id)
    assert user_id in connection_manager.active_connections

    await connection_manager.disconnect(mock_websocket, user_id)

    assert user_id not in connection_manager.active_connections
    mock_pubsub.unsubscribe.assert_awaited_with(f"notifications:user:{user_id}")


@pytest.mark.asyncio
async def test_disconnect_multiple_connections(
    connection_manager: ConnectionManager, mock_websocket: AsyncMock, mock_redis_pubsub: Any
) -> None:  # pylint: disable=redefined-outer-name
    """Test user disconnection (multiple connections)."""
    mock_pubsub, _ = mock_redis_pubsub
    user_id = uuid4()
    ws2 = AsyncMock(spec=WebSocket)

    # Connect two sockets
    await connection_manager.connect(mock_websocket, user_id)
    await connection_manager.connect(ws2, user_id)

    # Disconnect one
    await connection_manager.disconnect(mock_websocket, user_id)

    assert user_id in connection_manager.active_connections
    assert len(connection_manager.active_connections[user_id]) == 1
    # Should NOT have unsubscribed yet
    mock_pubsub.unsubscribe.assert_not_called()


@pytest.mark.asyncio
async def test_send_personal_message(connection_manager: ConnectionManager, mock_redis_pubsub: Any) -> None:  # pylint: disable=redefined-outer-name
    """Test sending personal message via Redis."""
    _, mock_redis = mock_redis_pubsub
    user_id = uuid4()
    message = "Hello"

    await connection_manager.send_personal_message(message, user_id)

    mock_redis.client.publish.assert_awaited_once_with(f"notifications:user:{user_id}", message)


@pytest.mark.asyncio
async def test_broadcast(connection_manager: ConnectionManager, mock_redis_pubsub: Any) -> None:  # pylint: disable=redefined-outer-name
    """Test broadcasting message via Redis."""
    _, mock_redis = mock_redis_pubsub
    message = "Global Alert"

    await connection_manager.broadcast(message)

    mock_redis.client.publish.assert_awaited_once_with("notifications:broadcast", message)


@pytest.mark.asyncio
async def test_redis_listener_local_broadcast(
    connection_manager: ConnectionManager, mock_websocket: AsyncMock, mock_redis_pubsub: Any
) -> None:  # pylint: disable=redefined-outer-name, unused-argument
    """Test receiving broadcast from Redis."""
    mock_pubsub, _ = mock_redis_pubsub
    user_id = uuid4()
    message_content = "Broadcast Message"

    # Setup connection
    await connection_manager.connect(mock_websocket, user_id)

    # Prepare mock message
    mock_message = {"type": "message", "channel": "notifications:broadcast", "data": message_content}

    # Simulate receiving message
    async def mock_listen_gen() -> Any:
        yield mock_message

    mock_pubsub.listen = MagicMock(return_value=mock_listen_gen())

    # Manually trigger processing
    await connection_manager._local_broadcast(message_content)  # pylint: disable=protected-access

    mock_websocket.send_text.assert_awaited_with(message_content)


@pytest.mark.asyncio
async def test_redis_listener_local_send(
    connection_manager: ConnectionManager, mock_websocket: AsyncMock, mock_redis_pubsub: Any
) -> None:  # pylint: disable=redefined-outer-name, unused-argument
    """Test receiving personal message from Redis."""
    user_id = uuid4()
    message_content = "Personal Message"

    # Setup connection
    await connection_manager.connect(mock_websocket, user_id)

    await connection_manager._local_send(message_content, user_id)  # pylint: disable=protected-access

    mock_websocket.send_text.assert_awaited_with(message_content)
