import logging

from api.apps.notification.v0.listeners.utils import dispatch_user_notification
from api.apps.notification.v0.schemas import NotificationType
from api.core.events.bus import event_bus
from api.core.events.constants import EventNames
from api.core.events.schema import ApplicationEvent

logger = logging.getLogger("fastapi")


@event_bus.on(EventNames.USER_PASSWORD_CHANGED)
async def on_password_changed(event: ApplicationEvent) -> None:
    """
    Subscriber for the user.password.changed event.
    Dispatches a security notification upon successful password change.

    Args:
        event (ApplicationEvent): The application event containing user_id, email, and username in its payload.
    """
    logger.info("Notification app received %s via EventBus.", event.event_name)

    await dispatch_user_notification(
        event=event,
        notification_type=NotificationType.WARNING,
        subject="Security Alert: Password Changed",
        message="Your password was successfully updated. "
        "If you did not make this change, please contact support immediately.",
        template_path="email/notification.html",
    )
