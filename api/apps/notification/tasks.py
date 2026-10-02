"""
Celery background dispatcher tasks for high-level notification events and broadcasts.
"""

import logging
from uuid import UUID

from api.apps.notification.v0.dao.device import DeviceDAO
from api.apps.notification.v0.schemas import NotificationType
from api.apps.notification.v0.service import NotificationService
from api.apps.notification.workers import send_email_worker_task, send_fcm_push_worker_task
from api.core.celery_app import AsyncBaseTask, celery_app

__all__ = [
    "send_notification_task",
    "broadcast_notification_task",
    "send_email_worker_task",
    "send_fcm_push_worker_task",
]

logger = logging.getLogger(__name__)


@celery_app.task(name="send_notification_task", bind=True)
def send_notification_task(
    self: AsyncBaseTask,
    user_id_str: str,
    message: str,
    notification_type: str = NotificationType.INFO.value,
    subject: str | None = None,
    metadata: dict | None = None,
    channels: list[str] | None = None,
) -> None:
    """
    Celery task to send a notification in the background.
    """
    logger.info("Executing task: send_notification_task for user %s", user_id_str)
    user_id = UUID(user_id_str)
    type_enum = NotificationType(notification_type)

    async def _send() -> None:
        service = NotificationService(device_dao=DeviceDAO(self.container.db))
        await service.notify(
            user_id=user_id,
            message=message,
            notification_type=type_enum,
            subject=subject,
            metadata=metadata,
            channels=channels,
        )

    coro = _send()
    try:
        self.loop.run_until_complete(coro)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        coro.close()
        logger.exception("Error sending background notification to user %s", user_id)


@celery_app.task(name="broadcast_notification_task", bind=True)
def broadcast_notification_task(
    self: AsyncBaseTask,
    message: str,
    notification_type: str = NotificationType.INFO.value,
    subject: str | None = None,
    metadata: dict | None = None,
    channels: list[str] | None = None,
) -> None:
    """
    Celery task to broadcast a notification in the background.
    """
    logger.info("Executing task: broadcast_notification_task")
    type_enum = NotificationType(notification_type)

    async def _broadcast() -> None:
        service = NotificationService(device_dao=DeviceDAO(self.container.db))
        await service.broadcast_all(
            message=message,
            notification_type=type_enum,
            subject=subject,
            metadata=metadata,
            channels=channels,
        )

    coro = _broadcast()
    try:
        self.loop.run_until_complete(coro)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        coro.close()
        logger.exception("Error broadcasting background notification")
