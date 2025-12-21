import logging
from typing import List, Optional
from uuid import UUID

from api.apps.notification.schemas import NotificationSchema, NotificationType
from api.apps.notification.v0.channels.base import BaseNotificationChannel
from api.apps.notification.v0.channels.websocket import websocket_channel

log = logging.getLogger("fastapi")


class NotificationService:
    """
    Service to dispatch notifications to registered channels.
    """

    def __init__(self) -> None:
        self.channels: List[BaseNotificationChannel] = []
        # Register default channels
        self.register_channel(websocket_channel)

    def register_channel(self, channel: BaseNotificationChannel) -> None:
        """Register a notification channel."""
        self.channels.append(channel)

    async def notify(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        user_id: UUID,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        subject: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Send a notification to a user via all registered channels.
        """
        notification = NotificationSchema(
            type=notification_type,
            message=message,
            subject=subject,
            metadata=metadata or {},
        )

        for channel in self.channels:
            try:
                await channel.send(user_id, notification)
            except Exception:  # pylint: disable=broad-except
                log.error("Failed to send notification to channel %s", channel)

    async def broadcast_all(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        subject: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Broadcast a notification to all users via all registered channels.
        """
        notification = NotificationSchema(
            type=notification_type,
            message=message,
            subject=subject,
            metadata=metadata or {},
        )

        for channel in self.channels:
            try:
                await channel.broadcast(notification)
            except Exception:  # pylint: disable=broad-except
                log.error("Failed to broadcast notification to channel %s", channel)


notification_service = NotificationService()
