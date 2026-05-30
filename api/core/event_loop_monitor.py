import asyncio
import logging

from api.core.metrics import ASYNCIO_ACTIVE_TASKS, EVENT_LOOP_LAG_SECONDS

logger = logging.getLogger("fastapi")


async def monitor_event_loop(interval: float = 1.0) -> None:
    """
    Monitor the asyncio event loop health by measuring lag and active tasks.

    Lag is measured by checking the delay between scheduled sleep and actual wake-up.
    Active tasks count is fetched using asyncio.all_tasks().
    """
    loop = asyncio.get_running_loop()
    while True:
        try:
            start_time = loop.time()
            await asyncio.sleep(interval)
            end_time = loop.time()

            # Lag is the difference between actual elapsed time and expected sleep interval
            actual_elapsed = end_time - start_time
            lag = max(0.0, actual_elapsed - interval)

            EVENT_LOOP_LAG_SECONDS.set(lag)

            # Active asyncio tasks count
            active_tasks = len(asyncio.all_tasks())
            ASYNCIO_ACTIVE_TASKS.set(active_tasks)

        except asyncio.CancelledError:
            logger.info("Event loop monitor stopped")
            break
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Error in event loop monitor: %s", e, exc_info=True)
            await asyncio.sleep(interval)
