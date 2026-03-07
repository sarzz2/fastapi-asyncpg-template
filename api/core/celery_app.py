import asyncio
import logging
import os
from typing import cast

from celery import Celery, Task
from celery.schedules import crontab
from celery.signals import worker_process_init, worker_process_shutdown

from api.core.config import settings
from api.core.database import DataBase
from api.core.redis import RedisClient

log = logging.getLogger(__name__)


def autodiscover_tasks() -> list[str]:
    """
    Automatically discover and include Celery task modules.

    Scans for tasks in two locations:
    1. `tasks.py` inside each app directory (e.g., `api/apps/user/tasks.py`).
    2. Any Python file inside the shared `api/tasks/` directory.

    Returns:
        A list of module paths to be included by Celery.
    """
    task_modules = []
    # Discover tasks in app-specific 'tasks.py'
    apps_dir = os.path.join("api", "apps")
    if os.path.isdir(apps_dir):
        for app_name in os.listdir(apps_dir):
            if os.path.isdir(os.path.join(apps_dir, app_name)) and os.path.exists(
                os.path.join(apps_dir, app_name, "tasks.py")
            ):
                task_modules.append(f"api.apps.{app_name}.tasks")

    # Discover tasks in the shared 'api/tasks' directory
    shared_tasks_dir = os.path.join("api", "tasks")
    if os.path.isdir(shared_tasks_dir):
        for filename in os.listdir(shared_tasks_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_name = filename[:-3]  # remove .py
                task_modules.append(f"api.tasks.{module_name}")
    return task_modules


# Initialize Celery
celery_app = Celery(
    "worker",
    broker=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_CELERY_BROKER}",
    backend=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_CELERY_BACKEND}",
    include=autodiscover_tasks(),
)

# Celery Configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_concurrency=1,  # Adjust as needed
    worker_prefetch_multiplier=1,
)


@worker_process_init.connect
def init_worker_process(**_kwargs: dict) -> None:
    """Initialize resources for each worker process."""
    log.info("Initializing worker process resources...")

    celery_app.main_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(celery_app.main_loop)

    celery_app.db_instance = DataBase()
    celery_app.main_loop.run_until_complete(
        celery_app.db_instance.create_pool(
            write_uri=settings.PRIMARY_DATABASE_URL,
            read_uris={"global": [settings.REPLICA_DATABASE_URL]},
            loop=celery_app.main_loop,
        )
    )

    celery_app.redis_instance = RedisClient()
    celery_app.main_loop.run_until_complete(celery_app.redis_instance.connect())
    log.info("Worker process resources initialized.")


@worker_process_shutdown.connect
def shutdown_worker_process(**_kwargs: dict) -> None:
    """Clean up resources when a worker process shuts down."""
    log.info("Shutting down worker process resources...")
    if hasattr(celery_app, "main_loop") and hasattr(celery_app, "db_instance"):
        celery_app.main_loop.run_until_complete(celery_app.db_instance.close_pool())
    if hasattr(celery_app, "main_loop") and hasattr(celery_app, "redis_instance"):
        celery_app.main_loop.run_until_complete(celery_app.redis_instance.close())
    log.info("Worker process resources shut down.")


class AsyncBaseTask(Task):  # pylint: disable=abstract-method
    """
    An abstract Celery Task class that provides database and Redis connections.
    """

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Provides the worker's main event loop."""
        if not hasattr(self.app, "main_loop"):
            raise RuntimeError("Event loop not initialized for worker process.")
        return cast(asyncio.AbstractEventLoop, self.app.main_loop)

    @property
    def db(self) -> DataBase:
        """Provides the shared database connection pool instance for the worker."""
        return cast(DataBase, self.app.db_instance)

    @property
    def redis(self) -> RedisClient:
        """Provides the shared Redis client instance for the worker."""
        return cast(RedisClient, self.app.redis_instance)


celery_app.Task = AsyncBaseTask


# Celery Beat Schedule
celery_app.conf.beat_schedule = {
    "delete-stagnant-s3-files": {
        "task": "api.tasks.delete_s3_files.delete_stagnant_temporary_files",
        "schedule": crontab(minute="*/15"),  # Runs every 15 minutes
    },
    "delete-old-logs": {
        "task": "api.tasks.delete_old_logs.delete_old_logs",
        "schedule": crontab(minute=0, hour=0),  # Runs midnight daily
    },
}
