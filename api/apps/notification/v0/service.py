import asyncio
import logging
from typing import AsyncGenerator
from uuid import UUID

from fastapi import Depends, Request

from api.apps.common.constants import NotificationChannels
from api.apps.notification.v0.channels.base import BaseNotificationChannel
from api.apps.notification.v0.channels.email import email_channel
from api.apps.notification.v0.channels.fcm import fcm_channel
from api.apps.notification.v0.channels.sse import sse_channel
from api.apps.notification.v0.dao.device import DeviceDAO, get_device_dao
from api.apps.notification.v0.schemas import DeviceResponse, NotificationSchema, NotificationType
from api.core.redis import redis_socket
from api.shared.redis_keys import RedisKeys

logger = logging.getLogger("fastapi")


class NotificationService:
    """
    Service to dispatch notifications to registered channels and manage push devices.
    """

    def __init__(self, device_dao: DeviceDAO) -> None:
        self.device_dao = device_dao
        self.channels: dict[str, BaseNotificationChannel] = {}
        # Register default channels
        self.register_channel(NotificationChannels.SSE.value, sse_channel)
        self.register_channel(NotificationChannels.EMAIL.value, email_channel)
        self.register_channel(NotificationChannels.FCM.value, fcm_channel)

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
        subject: str | None = None,
        metadata: dict | None = None,
        action_url: str | None = None,
        template_path: str = "email/notification.html",
        channels: list[str | NotificationChannels] | None = None,
    ) -> None:
        """
        Send a notification to a user via all registered channels (or specified channels).

        Args:
            user_id (UUID): User ID.
            message (str): Message to send.
            notification_type (NotificationType): Type of notification.
            subject (str | None): Subject of the notification.
            metadata (dict | None): Metadata of the notification.
            action_url (str | None): Action URL of the notification.
            template_path (str): Template path of the notification.
            channels (list[str | NotificationChannels] | None): Channels to send to (sends to all if None).
        """
        logger.debug("Dispatching notification to user %s (type=%s)", user_id, notification_type.value)
        notification = NotificationSchema(
            type=notification_type,
            message=message,
            subject=subject,
            metadata=metadata or {},
            action_url=action_url,
            template_path=template_path,
        )

        if channels is None:
            target_channels = list(self.channels.values())
        else:
            channel_names = [c.value if hasattr(c, "value") else str(c) for c in channels]
            target_channels = [self.channels[c] for c in channel_names if c in self.channels]

        for channel in target_channels:
            try:
                await channel.send(user_id, notification)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Failed to send notification to channel %s", channel)

    async def broadcast_all(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        subject: str | None = None,
        metadata: dict | None = None,
        action_url: str | None = None,
        template_path: str = "email/notification.html",
        channels: list[str | NotificationChannels] | None = None,
    ) -> None:
        """
        Broadcast a notification to all users via all registered channels (or specified channels).

        Args:
            message (str): Message to send.
            notification_type (NotificationType): Type of notification.
            subject (str | None): Subject of the notification.
            metadata (dict | None): Metadata of the notification.
            action_url (str | None): Action URL of the notification.
            template_path (str): Template path of the notification.
            channels (list[str | NotificationChannels] | None): Channels to broadcast to (sends to all if None).
        """
        logger.debug("Broadcasting notification (type=%s)", notification_type.value)
        notification = NotificationSchema(
            type=notification_type,
            message=message,
            subject=subject,
            metadata=metadata or {},
            action_url=action_url,
            template_path=template_path,
        )

        if channels is None:
            target_channels = list(self.channels.values())
        else:
            channel_names = [c.value if hasattr(c, "value") else str(c) for c in channels]
            target_channels = [self.channels[c] for c in channel_names if c in self.channels]

        for channel in target_channels:
            try:
                await channel.broadcast(notification)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Failed to broadcast notification to channel %s", channel)

    async def stream_sse(self, request: Request, user_id: UUID) -> AsyncGenerator[str, None]:
        """
        Stream Server-Sent Events from Redis Pub/Sub channels to client.
        Sends periodic ': ping\\n\\n' comment lines to prevent proxy timeouts.

        Args:
            request (Request): FastAPI request object to monitor client disconnection.
            user_id (UUID): User ID to stream notifications for.

        Yields:
            AsyncGenerator[str, None]: SSE formatted strings.
        """
        pubsub = redis_socket.client.pubsub()
        user_channel = RedisKeys.NOTIFICATION_USER_CHANNEL.format(user_id=str(user_id))
        broadcast_channel = RedisKeys.NOTIFICATION_BROADCAST_CHANNEL
        await pubsub.subscribe(user_channel, broadcast_channel)
        logger.info("SSE client connected for user: %s", user_id)

        try:
            while True:
                if await request.is_disconnected():
                    logger.info("SSE client disconnected for user: %s", user_id)
                    break

                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                except asyncio.CancelledError:
                    break

                if message and message.get("type") == "message":
                    data = message.get("data", "")
                    yield f"event: notification\ndata: {data}\n\n"
                else:
                    yield ": ping\n\n"
        finally:
            await pubsub.unsubscribe(user_channel, broadcast_channel)
            await pubsub.aclose()

    async def register_device(
        self,
        user_id: UUID,
        fcm_token: str,
        platform: str,
        device_name: str | None = None,
    ) -> DeviceResponse:
        """
        Register or reactivate a push device token for a user.

        Args:
            user_id: UUID of user.
            fcm_token: FCM device token.
            platform: Platform ('ios', 'android', 'web').
            device_name: Optional device descriptor.

        Returns:
            DeviceResponse: Registered device record.
        """
        return await self.device_dao.register_device(
            user_id=user_id,
            fcm_token=fcm_token,
            platform=platform,
            device_name=device_name,
        )

    async def unregister_device(self, user_id: UUID, fcm_token: str) -> None:
        """
        Unregister a push notification device token for a user.

        Args:
            user_id: UUID of user.
            fcm_token: FCM token to deactivate.
        """
        await self.device_dao.unregister_device(user_id=user_id, fcm_token=fcm_token)

    async def get_user_devices(self, user_id: UUID) -> list[DeviceResponse]:
        """
        Get all active push devices registered for a user.

        Args:
            user_id: UUID of user.

        Returns:
            list[DeviceResponse]: List of active user devices.
        """
        return await self.device_dao.get_active_devices_by_user(user_id)


def get_notification_service(
    device_dao: DeviceDAO = Depends(get_device_dao),
) -> NotificationService:
    """
    Dependency to get the Notification Service.
    """
    return NotificationService(device_dao=device_dao)
