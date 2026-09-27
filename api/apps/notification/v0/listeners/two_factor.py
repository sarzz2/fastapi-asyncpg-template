import logging

from api.apps.notification.v0.listeners.utils import dispatch_user_notification
from api.apps.notification.v0.schemas import NotificationType
from api.core.events.bus import event_bus
from api.core.events.constants import EventNames
from api.core.events.schema import ApplicationEvent

logger = logging.getLogger("fastapi")


@event_bus.on(EventNames.USER_2FA_ENABLED)
async def on_two_factor_enabled(event: ApplicationEvent) -> None:
    """
    Subscriber for the user.2fa.enabled event.
    Dispatches a security notification upon successful 2FA enablement.

    Args:
        event (ApplicationEvent): The application event containing user_id, email, and username.
    """
    logger.info("Notification app received %s via EventBus.", event.event_name)

    await dispatch_user_notification(
        event=event,
        notification_type=NotificationType.SUCCESS,
        subject="Security Alert: Two-Factor Authentication Enabled",
        message="Two-Factor Authentication (2FA) was successfully enabled on your account. "
        "If you did not make this change, please contact support immediately.",
        template_path="email/notification.html",
    )


@event_bus.on(EventNames.USER_2FA_DISABLED)
async def on_two_factor_disabled(event: ApplicationEvent) -> None:
    """
    Subscriber for the user.2fa.disabled event.
    Dispatches a security notification upon 2FA disablement.

    Args:
        event (ApplicationEvent): The application event containing user_id, email, and username.
    """
    logger.info("Notification app received %s via EventBus.", event.event_name)

    await dispatch_user_notification(
        event=event,
        notification_type=NotificationType.WARNING,
        subject="Security Alert: Two-Factor Authentication Disabled",
        message="Two-Factor Authentication (2FA) was disabled on your account. "
        "If you did not make this change, please contact support immediately.",
        template_path="email/notification.html",
    )
