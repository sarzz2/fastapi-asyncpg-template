import logging
from uuid import UUID

from api.apps.common.constants import NotificationChannels
from api.apps.notification.v0.dao.device import DeviceDAO
from api.apps.notification.v0.schemas import NotificationType
from api.apps.notification.v0.service import NotificationService
from api.core.config import settings
from api.core.database import DataBase
from api.core.events.schema import ApplicationEvent

logger = logging.getLogger("fastapi")


async def dispatch_user_notification(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    event: ApplicationEvent,
    notification_type: NotificationType,
    subject: str,
    message: str,
    template_path: str,
    action_url: str = settings.FRONTEND_URL,
    channels: list[str | NotificationChannels] | None = None,
) -> None:
    """
    Helper function to extract standard user payload fields and send a notification.
    """
    user_id_str = event.payload.get("user_id")
    email = event.payload.get("email")
    username = event.payload.get("username")

    if not user_id_str or not email or not username:
        logger.error("Missing required user data in %s payload.", event.event_name)
        return

    try:
        user_id = UUID(user_id_str)
    except ValueError:
        logger.error("Invalid user_id UUID format in %s payload.", event.event_name)
        return

    selected_channels = channels or [
        NotificationChannels.EMAIL.value,
        NotificationChannels.SSE.value,
        NotificationChannels.FCM.value,
    ]

    service = NotificationService(device_dao=DeviceDAO(DataBase()))
    await service.notify(
        user_id=user_id,
        notification_type=notification_type,
        subject=subject,
        message=message,
        template_path=template_path,
        action_url=action_url,
        metadata={
            "email": email,
            "username": username,
        },
        channels=selected_channels,
    )
