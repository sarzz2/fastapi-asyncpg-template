import logging
from typing import List, Optional
from uuid import UUID

from api.apps.notification.schemas import NotificationSchema, NotificationType
from api.apps.notification.v0.channels.base import BaseNotificationChannel
from api.apps.notification.v0.channels.email import email_channel
from api.apps.notification.v0.channels.websocket import websocket_channel

log = logging.getLogger("fastapi")


class NotificationService:
    """
    Service to dispatch notifications to registered channels.
    """

    def __init__(self) -> None:
        self.channels: dict[str, BaseNotificationChannel] = {}
        # Register default channels
        self.register_channel("websocket", websocket_channel)
        self.register_channel("email", email_channel)

    def register_channel(self, name: str, channel: BaseNotificationChannel) -> None:
        """
        Register a notification channel.

        Args:
            name (str): Name of the channel.
            channel (BaseNotificationChannel): Channel to register.
        """
        if name in self.channels:
            return
        self.channels[name] = channel

    async def notify(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        user_id: UUID,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        subject: Optional[str] = None,
        metadata: Optional[dict] = None,
        action_url: Optional[str] = None,
        template_path: str = "email/notification.html",
        channels: Optional[List[str]] = None,
    ) -> None:
        """
        Send a notification to a user via all registered channels.

        Args:
            user_id (UUID): User ID.
            message (str): Message to send.
            notification_type (NotificationType): Type of notification.
            subject (Optional[str]): Subject of the notification.
            metadata (Optional[dict]): Metadata of the notification.
            action_url (Optional[str]): Action URL of the notification.
            template_path (str): Template path of the notification.
            channels (Optional[List[str]]): Channels to send the notification to.
        """
        notification = NotificationSchema(
            type=notification_type,
            message=message,
            subject=subject,
            metadata=metadata or {},
            action_url=action_url,
            template_path=template_path,
        )

        target_channels = (
            [self.channels[c] for c in channels if c in self.channels]
            if channels is not None
            else list(self.channels.values())
        )

        for channel in target_channels:
            try:
                await channel.send(user_id, notification)
            except Exception:  # pylint: disable=broad-except
                log.exception("Failed to send notification to channel %s", channel)

    async def broadcast_all(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        subject: Optional[str] = None,
        metadata: Optional[dict] = None,
        action_url: Optional[str] = None,
        template_path: str = "email/notification.html",
        channels: Optional[List[str]] = None,
    ) -> None:
        """
        Broadcast a notification to all users via all registered channels.

        Args:
            message (str): Message to send.
            notification_type (NotificationType): Type of notification.
            subject (Optional[str]): Subject of the notification.
            metadata (Optional[dict]): Metadata of the notification.
            action_url (Optional[str]): Action URL of the notification.
            template_path (str): Template path of the notification.
            channels (Optional[List[str]]): Channels to send the notification to.
        """
        notification = NotificationSchema(
            type=notification_type,
            message=message,
            subject=subject,
            metadata=metadata or {},
            action_url=action_url,
            template_path=template_path,
        )

        target_channels = (
            [self.channels[c] for c in channels if c in self.channels]
            if channels is not None
            else list(self.channels.values())
        )

        for channel in target_channels:
            try:
                await channel.broadcast(notification)
            except Exception:  # pylint: disable=broad-except
                log.exception("Failed to broadcast notification to channel %s", channel)


notification_service = NotificationService()


def get_notification_service() -> NotificationService:
    """
    Dependency to get the Notification Service.
    """
    return notification_service
