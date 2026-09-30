from api.apps.common.v0.service.webhook import WebhookService
from api.core.events.bus import event_bus
from api.core.events.constants import EventNames
from api.core.events.schema import ApplicationEvent


async def handle_application_event(event: ApplicationEvent) -> None:
    """
    Generic subscriber handler to match and enqueue outbound webhooks
    for any registered domain EventName.

    Args:
        event (ApplicationEvent): The application event to handle.

    Returns:
        None
    """
    await WebhookService.dispatch_event_to_endpoints(
        event_name=event.event_name,
        payload=event.payload,
        event_id=str(event.event_id),
    )


# Explicitly subscribe to each defined EventName
for _event_member in EventNames:
    event_bus.subscribe(_event_member.value, handle_application_event)
