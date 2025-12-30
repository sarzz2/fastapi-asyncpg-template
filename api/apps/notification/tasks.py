import logging
from typing import Optional
from uuid import UUID

from celery import Task

from api.apps.notification.schemas import NotificationType
from api.apps.notification.v0.service import notification_service
from api.core.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="send_notification_task", bind=True)
def send_notification_task(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    self: Task,
    user_id_str: str,
    message: str,
    notification_type: str = NotificationType.INFO.value,
    subject: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """
    Celery task to send a notification background.
    """
    user_id = UUID(user_id_str)
    type_enum = NotificationType(notification_type)

    async def _send() -> None:
        await notification_service.notify(
            user_id=user_id,
            message=message,
            notification_type=type_enum,
            subject=subject,
            metadata=metadata,
        )

    try:
        # Use the worker's event loop to run the async method
        self.loop.run_until_complete(_send())
    except Exception as e:  # pylint: disable=broad-except
        log.error("Error sending background notification to user %s: %s", user_id, e)


@celery_app.task(name="broadcast_notification_task", bind=True)
def broadcast_notification_task(
    self: Task,
    message: str,
    notification_type: str = NotificationType.INFO.value,
    subject: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """
    Celery task to broadcast a notification in background.
    """
    type_enum = NotificationType(notification_type)

    async def _broadcast() -> None:
        await notification_service.broadcast_all(
            message=message,
            notification_type=type_enum,
            subject=subject,
            metadata=metadata,
        )

    try:
        self.loop.run_until_complete(_broadcast())
    except Exception as e:  # pylint: disable=broad-except
        log.error("Error broadcasting background notification: %s", e)
