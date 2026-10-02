import asyncio
import importlib
import logging
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from redis.exceptions import RedisError, ResponseError

from api.core.events.constants import EventNames
from api.core.events.schema import ApplicationEvent
from api.core.redis import redis_event_bus

logger = logging.getLogger("fastapi")


class EventBus:
    """
    A persistent, distributed event bus built on Redis Streams and Consumer Groups.
    Provides at-least-once message durability, load-balanced consumer dispatch,
    and automatic memory management via rolling stream trimming.
    """

    STREAM_NAME: str = "event_bus:stream"
    GROUP_NAME: str = "event_bus:workers"
    MAX_STREAM_LEN: int = 50000

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[ApplicationEvent], Any]]] = {}
        self.listener_task: asyncio.Task | None = None
        self.consumer_name: str = f"worker:{uuid4()}"
        self._running: bool = False

    async def start(self) -> None:
        """Starts the Redis Stream consumer group listener."""
        self._running = True
        try:
            await redis_event_bus.client.xgroup_create(
                name=self.STREAM_NAME,
                groupname=self.GROUP_NAME,
                id="$",
                mkstream=True,
            )
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                logger.error("Could not initialize Redis Stream group: %s", e)

        self.listener_task = asyncio.create_task(self._redis_listener())
        logger.info("EventBus Redis Stream listener started (consumer: %s).", self.consumer_name)

    async def stop(self) -> None:
        """Stops the Redis Stream listener."""
        self._running = False
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass
        logger.info("EventBus Redis Stream listener stopped.")

    async def _redis_listener(self) -> None:
        """Listens to the Redis Stream using consumer groups."""
        while self._running:
            try:
                entries: Any = await redis_event_bus.client.xreadgroup(
                    groupname=self.GROUP_NAME,
                    consumername=self.consumer_name,
                    streams={self.STREAM_NAME: ">"},
                    count=10,
                    block=2000,
                )
                if not entries:
                    continue

                for _stream_name, messages in entries:
                    for message_id, message_data in messages:
                        raw_data = message_data.get("data")
                        if raw_data:
                            await self._process_remote_event(raw_data)
                        await redis_event_bus.client.xack(self.STREAM_NAME, self.GROUP_NAME, message_id)
            except asyncio.CancelledError:
                break
            except (RedisError, ConnectionError, OSError) as err:
                logger.warning("EventBus Redis Stream listener error: %s", err)
                await asyncio.sleep(1)
            except Exception as e:  # pylint: disable=broad-except
                logger.error("EventBus unexpected listener error: %s", e)
                await asyncio.sleep(1)

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
        Automatically searches for listener files within 'api/apps/**/listeners/*.py' and imports them.
        This triggers any `@event_bus.on` decorators to register at startup, enforcing decoupled organization.
        """
        base_dir = Path(__file__).resolve().parent.parent.parent / "apps"
        if not base_dir.exists():
            logger.warning("No apps directory found")
            return

        logger.info("Initializing EventBus listener autodiscovery...")
        discovered_count = 0

        # Dynamically scan for any 'listeners' directory inside apps
        for listeners_dir in base_dir.rglob("listeners"):
            if not listeners_dir.is_dir():
                continue

            for listener_file in listeners_dir.rglob("*.py"):
                if listener_file.name == "__init__.py":
                    continue

                # Convert OS path to Python module string (e.g. api.apps.notification.v0.listeners.user_created)
                rel_path = listener_file.relative_to(base_dir.parent.parent)
                module_name = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")

                try:
                    importlib.import_module(module_name)
                    discovered_count += 1
                    logger.debug("EventBus imported listeners from %s", module_name)
                except Exception as e:  # pylint: disable=broad-except
                    logger.error("Failed to autodiscover listeners in %s: %s", module_name, e)

        logger.info("EventBus initialized. Loaded %d listener modules.", discovered_count)

    async def publish(self, event: ApplicationEvent) -> None:
        """
        Publish an event to the Redis EventBus Stream asynchronously.
        Args:
            event: The event to publish.
        """
        payload = event.model_dump_json()
        await redis_event_bus.client.xadd(
            self.STREAM_NAME,
            {"data": payload, "event_name": event.event_name, "event_id": str(event.event_id)},
            maxlen=self.MAX_STREAM_LEN,
            approximate=True,
        )
        logger.debug("Published %s to Redis Stream %s.", event.event_name, self.STREAM_NAME)

    async def _process_remote_event(self, raw_data: str) -> None:
        """Processes an event received from Redis Stream with idempotent deduplication."""
        try:
            event = ApplicationEvent.model_validate_json(raw_data)

            handlers = self._subscribers.get(event.event_name, [])
            if not handlers:
                return

            lock_key = f"event_bus:lock:{event.event_id}"
            acquired = await redis_event_bus.client.set(lock_key, "1", nx=True, ex=60)

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
