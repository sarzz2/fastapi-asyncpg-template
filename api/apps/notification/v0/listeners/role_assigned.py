# pylint: disable=duplicate-code
import logging

from api.apps.notification.v0.listeners.utils import dispatch_user_notification
from api.apps.notification.v0.schemas import NotificationType
from api.core.config import settings
from api.core.events.bus import event_bus
from api.core.events.constants import EventNames
from api.core.events.schema import ApplicationEvent

logger = logging.getLogger("fastapi")


@event_bus.on(EventNames.USER_ROLE_ASSIGNED)
async def on_role_assigned(event: ApplicationEvent) -> None:
    """
    Subscriber for the user.role.assigned event.
    Dispatches a notification letting the user know their access level was updated.

    Args:
        event (ApplicationEvent): The application event containing user_id, email,
                                    username, and role_ids in its payload.
    """
    logger.info("Notification app received %s via EventBus.", event.event_name)

    await dispatch_user_notification(
        event=event,
        notification_type=NotificationType.INFO,
        subject="Account Access Updated",
        message="An administrator has updated the roles assigned to your account.",
        template_path="email/notification.html",
        action_url=f"{settings.FRONTEND_URL}/dashboard",
    )
