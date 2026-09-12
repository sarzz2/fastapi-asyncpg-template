"""
Celery Application Initialization, Configuration, Signal Handlers, and DLQ Subsystem.
"""

import asyncio
import json
import logging
import os
import traceback as traceback_module
from typing import Any, cast

from celery import Celery, Task
from celery.signals import task_failure, worker_process_init, worker_process_shutdown
from opentelemetry.instrumentation.celery import CeleryInstrumentor

from api.apps.common.constants import DLQConstants
from api.core.config import settings
from api.core.database import DataBase
from api.core.redis import RedisClient
from api.utils.serialization import json_serialize_safe

log = logging.getLogger(__name__)


def autodiscover_tasks() -> list[str]:
    """
    Automatically discover and include Celery task modules.

    Scans for tasks in two locations:
    1. `tasks.py` inside each app directory (e.g., `api/apps/user/tasks.py`).
    2. Any Python file inside the shared `api/tasks/` directory.

    Returns:
        list[str]: A list of dot-separated module paths to be included by Celery.
    """
    task_modules: list[str] = []

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
                module_name = filename[:-3]  # remove .py extension
                task_modules.append(f"api.tasks.{module_name}")

    log.info("Discovered Celery tasks in: %s", task_modules)
    return task_modules


# Initialize Celery Application
celery_app = Celery(
    "worker",
    broker=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_CELERY_BROKER}",
    backend=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_CELERY_BACKEND}",
    include=autodiscover_tasks(),
)

# Initialize worker resource attributes on celery_app
celery_app.main_loop = None
celery_app.db_instance = None
celery_app.redis_instance = None

celery_app.loader.import_default_modules()

CeleryInstrumentor().instrument()

# Celery Configuration
celery_app.conf.update(
    task_default_queue="default",
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_scheduler="api.core.celery_scheduler.DatabaseBeatScheduler",
    beat_max_loop_interval=5,
)


@worker_process_init.connect
def init_worker_process(**_kwargs: dict[str, Any]) -> None:
    """
    Initialize resources for each worker process (event loop, PostgreSQL pool, Redis client).

    Args:
        **_kwargs (dict[str, Any]): Additional signal parameters.
    """
    log.info("Initializing worker process resources...")

    main_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(main_loop)
    celery_app.main_loop = main_loop

    db_instance = DataBase()
    main_loop.run_until_complete(
        db_instance.create_pool(
            write_uri=settings.PRIMARY_DATABASE_URL,
            read_uris={"global": [settings.REPLICA_DATABASE_URL]},
            loop=main_loop,
        )
    )
    celery_app.db_instance = db_instance

    redis_instance = RedisClient()
    main_loop.run_until_complete(redis_instance.connect())
    celery_app.redis_instance = redis_instance

    log.info("Worker process resources initialized.")


@worker_process_shutdown.connect
def shutdown_worker_process(**_kwargs: dict[str, Any]) -> None:
    """
    Clean up resources when a worker process shuts down.

    Args:
        **_kwargs (dict[str, Any]): Additional signal parameters.
    """
    log.info("Shutting down worker process resources...")
    main_loop = celery_app.main_loop
    db_instance = celery_app.db_instance
    redis_instance = celery_app.redis_instance

    if main_loop and db_instance:
        main_loop.run_until_complete(db_instance.close_pool())
    if main_loop and redis_instance:
        main_loop.run_until_complete(redis_instance.close())

    log.info("Worker process resources shut down.")


class AsyncBaseTask(Task):  # pylint: disable=abstract-method
    """
    An abstract Celery Task class that provides database and Redis connections,
    as well as default retry options (exponential backoff and randomized jitter).
    """

    autoretry_for = (Exception,)
    max_retries = 3
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """
        Provides the worker's main event loop.

        Returns:
            asyncio.AbstractEventLoop: Worker event loop instance.

        Raises:
            RuntimeError: If event loop is not initialized.
        """
        main_loop = getattr(self.app, "main_loop", None)
        if not main_loop:
            raise RuntimeError("Event loop not initialized for worker process.")
        return cast(asyncio.AbstractEventLoop, main_loop)

    @property
    def db(self) -> DataBase:
        """
        Provides the shared database connection pool instance for the worker.

        Returns:
            DataBase: Shared database wrapper instance.

        Raises:
            RuntimeError: If database connection is not initialized.
        """
        db_instance = getattr(self.app, "db_instance", None)
        if not db_instance:
            raise RuntimeError("Database instance not initialized for worker process.")
        return cast(DataBase, db_instance)

    @property
    def redis(self) -> RedisClient:
        """
        Provides the shared Redis client instance for the worker.

        Returns:
            RedisClient: Shared Redis client instance.

        Raises:
            RuntimeError: If Redis instance is not initialized.
        """
        redis_instance = getattr(self.app, "redis_instance", None)
        if not redis_instance:
            raise RuntimeError("Redis instance not initialized for worker process.")
        return cast(RedisClient, redis_instance)


celery_app.Task = AsyncBaseTask


# ==============================================================================
# Dead Letter Queue (DLQ) Failure Signal Capture Subsystem
# ==============================================================================


def _format_task_traceback(exception: Exception | None, traceback: Any | None, einfo: Any | None) -> str:
    """Format traceback string from exception, traceback, or ExceptionInfo."""
    if einfo and hasattr(einfo, "traceback"):
        return str(einfo.traceback)
    if traceback:
        return "".join(traceback_module.format_tb(traceback))
    if exception:
        return "".join(traceback_module.format_exception(type(exception), exception, exception.__traceback__))
    return ""


async def _save_dead_letter_task(db_instance: DataBase, payload: dict[str, Any]) -> None:
    """
    Insert a failed task record into the dead_letter_tasks database table.

    Args:
        db_instance (DataBase): DataBase connection pool instance.
        payload (dict[str, Any]): Dictionary containing failure parameters.
    """
    query = """
        INSERT INTO dead_letter_tasks (
            task_id, task_name, queue, args, kwargs, headers,
            exception_type, exception_message, traceback, retry_count
        ) VALUES (
            $1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8, $9, $10
        );
    """
    try:
        await db_instance.execute(
            query,
            payload["task_id"],
            payload["task_name"],
            payload["queue"],
            json.dumps(json_serialize_safe(payload.get("args") or [])),
            json.dumps(json_serialize_safe(payload.get("kwargs") or {})),
            json.dumps(json_serialize_safe(payload.get("headers") or {})),
            payload["exception_type"],
            payload["exception_message"],
            payload["traceback"],
            payload["retry_count"],
        )
        log.info(
            "Successfully saved task failure to DLQ for task_id=%s (name=%s)",
            payload["task_id"],
            payload["task_name"],
        )
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Failed to write task %s failure to DLQ: %s", payload["task_id"], exc)


@task_failure.connect
def handle_task_failure(
    sender: Task | None = None,
    task_id: str | None = None,
    exception: Exception | None = None,
    args: tuple[Any, ...] | list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    traceback: Any | None = None,
    einfo: Any | None = None,
    **_extra: Any,
) -> None:
    """
    Celery signal handler triggered upon task execution failures.

    Persists failed task details into the dead_letter_tasks database table when retries are exhausted.

    Args:
        sender (Task | None): Celery task instance emitting the failure.
        task_id (str | None): Unique task UUID string.
        exception (Exception | None): Raised exception instance.
        args (tuple[Any, ...] | list[Any] | None): Task positional arguments.
        kwargs (dict[str, Any] | None): Task keyword arguments.
        traceback (Any | None): Traceback instance.
        einfo (Any | None): Celery ExceptionInfo wrapper object.
        **_extra (Any): Additional signal keyword arguments.
    """
    if not sender or not task_id:
        log.warning("Task failure signal ignored: missing sender or task_id (sender=%s, task_id=%s).", sender, task_id)
        return

    task_name = sender.name if hasattr(sender, "name") else str(sender)
    if task_name in DLQConstants.EXCLUDED_TASKS:
        log.debug("Task failure signal ignored for excluded DLQ task '%s'.", task_name)
        return

    db_instance = celery_app.db_instance
    if not db_instance:
        log.warning("Celery DLQ cannot record failure: db_instance not initialized.")
        return

    req = getattr(sender, "request", None)
    payload = {
        "task_id": str(task_id),
        "task_name": task_name,
        "queue": getattr(sender, "queue", None) or "default",
        "args": list(args) if args else [],
        "kwargs": dict(kwargs) if kwargs else {},
        "headers": getattr(req, "headers", {}) or {},
        "exception_type": type(exception).__name__ if exception else "UnknownException",
        "exception_message": str(exception) if exception else "Task failed without exception message",
        "traceback": _format_task_traceback(exception, traceback, einfo),
        "retry_count": getattr(req, "retries", 0),
    }

    main_loop = celery_app.main_loop
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(_save_dead_letter_task(db_instance, payload), main_loop)
    else:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        coro = _save_dead_letter_task(db_instance, payload)
        if loop.is_running():
            loop.create_task(coro)
        else:
            loop.run_until_complete(coro)
