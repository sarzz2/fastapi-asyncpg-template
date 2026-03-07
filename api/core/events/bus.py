import asyncio
import importlib
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from redis.asyncio.client import PubSub

from api.core.events.constants import EventNames
from api.core.events.schema import ApplicationEvent
from api.core.redis import listen_to_pubsub, redis_client

logger = logging.getLogger("fastapi")


class EventBus:
    """
    A lightweight, in-memory event bus for decoupling application components.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[ApplicationEvent], Any]]] = {}
        self.pubsub: PubSub = redis_client.client.pubsub()
        self.listener_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Starts the Redis Pub/Sub listener."""
        if self.pubsub:
            await self.pubsub.subscribe("event_bus:broadcast")
            self.listener_task = asyncio.create_task(self._redis_listener())
            logger.info("EventBus Redis listener started.")

    async def stop(self) -> None:
        """Stops the Redis Pub/Sub listener."""
        if self.pubsub:
            await self.pubsub.unsubscribe("event_bus:broadcast")
            await self.pubsub.close()
        if self.listener_task:
            self.listener_task.cancel()
        logger.info("EventBus Redis listener stopped.")

    async def _redis_listener(self) -> None:
        """Listens to Redis for broadcasted events."""
        try:
            async for channel, data in listen_to_pubsub(self.pubsub):
                if channel == "event_bus:broadcast":
                    await self._process_remote_event(data)
        except asyncio.CancelledError:
            pass
        except Exception as e:  # pylint: disable=broad-except
            logger.error("EventBus Redis listener error: %s", e)

    def on(self, event_name: EventNames | str) -> Callable:
        """
        Decorator to register a handler to an event securely.
        Args:
            event_name: The name of the event to subscribe to.
        Returns:
            A decorator that can be used to register a handler to an event.
        """
        event_str = event_name.value if isinstance(event_name, EventNames) else event_name

        def decorator(func: Callable[[ApplicationEvent], Any]) -> Callable:
            self.subscribe(event_str, func)
            return func

        return decorator

    def subscribe(self, event_name: str, handler: Callable[[ApplicationEvent], Any]) -> None:
        """
        Subscribe a handler function to a specific event name manually.
        Args:
            event_name: The name of the event to subscribe to.
            handler: The handler function to subscribe to the event.
        """
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        if handler not in self._subscribers[event_name]:
            self._subscribers[event_name].append(handler)
            logger.debug("Handler %s subscribed to event: %s", handler.__name__, event_name)

    def autodiscover(self) -> None:
        """
        Automatically searches for listener files within 'api/apps/*/v0/listeners/*.py' and imports them.
        This triggers any `@event_bus.on` decorators to register at startup, enforcing decoupled organization.
        """
        base_dir = Path(__file__).resolve().parent.parent.parent / "apps"
        if not base_dir.exists():
            logger.warning("No apps directory found")
            return

        logger.info("Initializing EventBus listener autodiscovery...")
        discovered_count = 0

        # Scan for structured listener folders dynamically
        for app_dir in base_dir.iterdir():
            if not app_dir.is_dir() or app_dir.name == "__pycache__":
                continue

            listeners_dir = app_dir / "v0" / "listeners"
            if not listeners_dir.exists():
                continue

            for listener_file in listeners_dir.rglob("*.py"):
                if listener_file.name == "__init__.py":
                    continue

                # Convert OS path to Python module string (e.g. api.apps.notification.v0.listeners.user_created)
                rel_path = listener_file.relative_to(base_dir.parent.parent)
                module_name = str(rel_path).replace(".py", "").replace("/", ".")

                try:
                    importlib.import_module(module_name)
                    discovered_count += 1
                    logger.debug("EventBus imported listeners from %s", module_name)
                except Exception as e:  # pylint: disable=broad-except
                    logger.error("Failed to autodiscover listeners in %s: %s", module_name, e)

        logger.info("EventBus initialized. Loaded %d listener modules.", discovered_count)

    async def publish(self, event: ApplicationEvent) -> None:
        """
        Publish an event to the Redis EventBus asynchronously.
        Args:
            event: The event to publish.
        """
        payload = event.model_dump_json()
        await redis_client.client.publish("event_bus:broadcast", payload)
        logger.debug("Published %s to Redis EventBus.", event.event_name)

    async def _process_remote_event(self, raw_data: str) -> None:
        """Processes an event received from Redis, using a lock to ensure exactly-once execution."""
        try:
            event = ApplicationEvent.model_validate_json(raw_data)

            handlers = self._subscribers.get(event.event_name, [])
            if not handlers:
                return

            lock_key = f"event_bus:lock:{event.event_id}"
            acquired = await redis_client.client.set(lock_key, "1", nx=True, ex=60)

            if not acquired:
                logger.debug("Event %s dropped. Lock already held by another worker.", event.event_id)
                return

            logger.info("Executing %d handlers for remote event %s", len(handlers), event.event_name)

            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:  # pylint: disable=broad-except
                    logger.error("Error executing %s for %s: %s", handler.__name__, event.event_name, e)

        except Exception as e:  # pylint: disable=broad-except
            logger.error("Failed to parse remote event from Redis: %s", e)


# Global singleton instance of the Event Bus
event_bus = EventBus()
