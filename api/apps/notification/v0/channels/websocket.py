import asyncio
import logging
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import WebSocket
from redis.asyncio.client import PubSub

from api.apps.notification.v0.channels.base import BaseNotificationChannel
from api.apps.notification.v0.schemas import NotificationSchema
from api.core.redis import listen_to_pubsub, redis_socket

logger = logging.getLogger("fastapi")


class ConnectionManager:
    """
    Manages active WebSocket connections and synchronizes via Redis Pub/Sub.
    """

    def __init__(self) -> None:
        # Maps user_id -> List of WebSockets
        self.active_connections: Dict[UUID, List[WebSocket]] = {}
        self.pubsub: Optional[PubSub] = None
        self.listener_task: Optional[asyncio.Task] = None

    async def _ensure_listener(self) -> None:
        """Start the Redis listener task if it's not running."""
        if self.listener_task is None or self.listener_task.done():
            if self.pubsub is None:
                self.pubsub = redis_socket.client.pubsub()

            if self.pubsub:
                # Subscribe to broadcast channel by default
                await self.pubsub.subscribe("notifications:broadcast")
                self.listener_task = asyncio.create_task(self._redis_listener())
                logger.info("Redis Pub/Sub listener started.")

    async def stop(self) -> None:
        """Stop the Redis listener task and close Pub/Sub."""
        if self.pubsub:
            await self.pubsub.unsubscribe("notifications:broadcast")
            await self.pubsub.aclose()
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass
        logger.info("Redis Pub/Sub listener stopped.")

    async def _redis_listener(self) -> None:
        """Listen for messages from Redis and dispatch to local connections."""
        try:
            async for channel, data in listen_to_pubsub(self.pubsub):
                if channel == "notifications:broadcast":
                    await self._local_broadcast(data)
                elif channel.startswith("notifications:user:"):
                    user_id_str = channel.split(":")[-1]
                    try:
                        user_id = UUID(user_id_str)
                        await self._local_send(data, user_id)
                    except ValueError:
                        logger.error("Invalid user ID in channel: %s", channel)
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Redis listener error: %s", e)
            # Optional: Implement reconnection logic here if needed

    async def connect(self, websocket: WebSocket, user_id: UUID) -> None:
        """Accept connection and subscribe user to Redis channel."""
        await websocket.accept()

        if user_id not in self.active_connections:
            self.active_connections[user_id] = []

        self.active_connections[user_id].append(websocket)
        logger.info("User %s connected. Total connections: %s", user_id, len(self.active_connections.get(user_id, [])))

        # Ensure we are listening to Redis
        await self._ensure_listener()

        # Subscribe to user-specific channel if this is their first connection on this worker
        if len(self.active_connections[user_id]) == 1:
            if self.pubsub is not None:
                await self.pubsub.subscribe(f"notifications:user:{user_id}")

    async def disconnect(self, websocket: WebSocket, user_id: UUID) -> None:
        """Remove connection and unsubscribe if last one for user."""
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)

            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
                # Unsubscribe from Redis if no more connections for this user on this worker
                if self.pubsub is not None:
                    await self.pubsub.unsubscribe(f"notifications:user:{user_id}")

        logger.info("User %s disconnected.", user_id)

    async def send_personal_message(self, message: str, user_id: UUID) -> None:
        """Publish message to user's Redis channel."""
        # Instead of sending directly, we publish to Redis.
        # Any worker (including this one) with a connection for this user will pick it up.
        logger.debug("Publishing personal message to Redis for user: %s", user_id)
        await redis_socket.client.publish(f"notifications:user:{user_id}", message)

    async def broadcast(self, message: str) -> None:
        """Publish message to broadcast Redis channel."""
        logger.debug("Publishing broadcast message to Redis")
        await redis_socket.client.publish("notifications:broadcast", message)

    async def _local_send(self, message: str, user_id: UUID) -> None:
        """Send message to locally connected user (internal use)."""
        if user_id in self.active_connections:
            for connection in list(self.active_connections[user_id]):
                try:
                    await connection.send_text(message)
                except Exception as e:  # pylint: disable=broad-except
                    logger.error("Error sending to user %s: %s. Cleaning up.", user_id, e)
                    await self.disconnect(connection, user_id)

    async def _local_broadcast(self, message: str) -> None:
        """Send message to all locally connected users (internal use)."""
        for user_id in list(self.active_connections.keys()):
            await self._local_send(message, user_id)


class WebSocketChannel(BaseNotificationChannel):
    """
    Notification channel that sends messages via WebSocket.
    """

    def __init__(self, manager: ConnectionManager):
        self.manager = manager

    async def send(self, user_id: UUID, notification: NotificationSchema) -> None:
        """
        Send a notification to a specific user via WebSocket.
        Args:
            user_id: The user ID.
            notification: The notification to send.
        """
        # Convert schema to JSON string for transmission
        message = notification.model_dump_json()
        await self.manager.send_personal_message(message, user_id)

    async def broadcast(self, notification: NotificationSchema) -> None:
        """
        Broadcast a notification to all users via WebSocket.
        Args:
             notification: The notification to send.
        """
        message = notification.model_dump_json()
        await self.manager.broadcast(message)


# Global instance
connection_manager = ConnectionManager()
websocket_channel = WebSocketChannel(connection_manager)
