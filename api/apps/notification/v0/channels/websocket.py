import logging
from typing import Dict, List
from uuid import UUID

from fastapi import WebSocket

from api.apps.notification.schemas import NotificationSchema
from api.apps.notification.v0.channels.base import BaseNotificationChannel

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages active WebSocket connections.
    """

    def __init__(self) -> None:
        # Maps user_id -> List of WebSockets (supporting multiple devices per user)
        self.active_connections: Dict[UUID, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: UUID) -> None:
        """
        Accept the WebSocket connection.
        Args:
            websocket: The WebSocket connection.
            user_id: The user ID.
        """
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info("User %s connected. Total connections: %s", user_id, len(self.active_connections.get(user_id, [])))

    def disconnect(self, websocket: WebSocket, user_id: UUID) -> None:
        """
        Remove the WebSocket connection.
        Args:
            websocket: The WebSocket connection.
            user_id: The user ID.
        """
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info("User %s disconnected.", user_id)

    async def send_personal_message(self, message: str, user_id: UUID) -> None:
        """
        Send a message to a specific user.
        Args:
            message: The message to send.
            user_id: The user ID.
        """
        if user_id in self.active_connections:
            # Broadcast to all connections for this user
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_text(message)
                except Exception as e:  # pylint: disable=broad-except
                    logger.error("Error sending message to user %s: %s", user_id, e)

    async def broadcast(self, message: str) -> None:
        """
        Broadcast a message to all connected users.
        Args:
            message: The message to send.
        """
        for user_id, connections in self.active_connections.items():
            for connection in connections:
                try:
                    await connection.send_text(message)
                except Exception as e:  # pylint: disable=broad-except
                    logger.error("Error broadcasting to user %s: %s", user_id, e)


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
