import logging
from uuid import UUID

from api.apps.notification.v0.channels.base import BaseNotificationChannel
from api.apps.notification.v0.dao.device import DeviceDAO
from api.apps.notification.v0.schemas import NotificationSchema
from api.apps.notification.workers import send_fcm_push_worker_task
from api.core.database import DataBase

logger = logging.getLogger("fastapi")


class FCMChannel(BaseNotificationChannel):
    """
    Notification channel that dispatches push notifications to user devices via FCM Celery task.
    """

    def __init__(self, db: DataBase | None = None):
        self.db = db or DataBase()

    async def send(self, user_id: UUID, notification: NotificationSchema) -> None:
        """
        Send push notification to all active devices registered to this user.
        Args:
            user_id: UUID of the user to send notification to
            notification: NotificationSchema to send
        """
        dao = DeviceDAO(self.db)
        devices = await dao.get_active_devices_by_user(user_id)
        if not devices:
            logger.debug("FCMChannel skipped: No active devices found for user %s", user_id)
            return

        tokens = [d.fcm_token for d in devices]
        send_fcm_push_worker_task.delay(
            tokens=tokens,
            title=notification.subject,
            body=notification.message,
            data=notification.metadata,
        )

    async def broadcast(self, notification: NotificationSchema) -> None:
        """
        Broadcast push notification to all registered active devices across the application.
        Args:
            notification: NotificationSchema to send
        """
        dao = DeviceDAO(self.db)
        tokens = await dao.get_all_active_tokens()
        if not tokens:
            logger.debug("FCMChannel broadcast skipped: No active devices in database")
            return

        send_fcm_push_worker_task.delay(
            tokens=tokens,
            title=notification.subject,
            body=notification.message,
            data=notification.metadata,
        )


fcm_channel = FCMChannel()
