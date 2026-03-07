import logging

from api.apps.notification.schemas import NotificationType
from api.apps.notification.v0.listeners.utils import dispatch_user_notification
from api.core.events.bus import event_bus
from api.core.events.constants import EventNames
from api.core.events.schema import ApplicationEvent

logger = logging.getLogger("fastapi")


@event_bus.on(EventNames.USER_CREATED)
async def on_user_created(event: ApplicationEvent) -> None:
    """
    Subscriber for the user.created event.
    Dispatches the welcome registration email securely via Autodiscovery.
    """
    logger.info("Notification app received %s via EventBus.", event.event_name)

    await dispatch_user_notification(
        event=event,
        notification_type=NotificationType.INFO,
        subject="Welcome to FastAPI Template!",
        message="Your registration was successful.",
        template_path="email/welcome.html",
    )
