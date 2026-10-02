import logging
from uuid import UUID

from api.apps.notification.v0.channels.base import BaseNotificationChannel
from api.apps.notification.v0.schemas import NotificationSchema
from api.core.redis import redis_socket
from api.shared.redis_keys import RedisKeys

logger = logging.getLogger("fastapi")


class SSEChannel(BaseNotificationChannel):
    """
    Notification channel that dispatches messages to Redis Pub/Sub
    for delivery to active Server-Sent Events (SSE) subscriber streams.
    """

    async def send(self, user_id: UUID, notification: NotificationSchema) -> None:
        """
        Send a notification to a specific user via SSE Redis Pub/Sub stream.

        Args:
            user_id: UUID of the user to send notification to
            notification: NotificationSchema to send
        """
        message = notification.model_dump_json()
        logger.debug("Publishing SSE message to Redis for user: %s", user_id)
        channel_name = RedisKeys.NOTIFICATION_USER_CHANNEL.format(user_id=str(user_id))
        await redis_socket.client.publish(channel_name, message)

    async def broadcast(self, notification: NotificationSchema) -> None:
        """
        Broadcast a notification to all users via SSE Redis Pub/Sub stream.

        Args:
            notification: NotificationSchema to send
        """
        message = notification.model_dump_json()
        logger.debug("Publishing broadcast SSE message to Redis")
        await redis_socket.client.publish(RedisKeys.NOTIFICATION_BROADCAST_CHANNEL, message)


sse_channel = SSEChannel()
