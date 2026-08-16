import logging
from uuid import UUID

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis

from api.apps.common.constants import CeleryRedisKeys
from api.apps.common.v0.dao.periodic_task import PeriodicTaskDAO, get_periodic_task_dao
from api.apps.common.v0.schemas.periodic_task import PeriodicTaskCreate, PeriodicTaskResponse, PeriodicTaskUpdate
from api.core.celery_app import celery_app
from api.core.redis import get_redis

log = logging.getLogger(__name__)


class PeriodicTaskService:
    """Service layer for managing dynamic periodic Celery tasks and on-demand execution."""

    def __init__(self, dao: PeriodicTaskDAO, redis_client: Redis) -> None:
        """
        Initialize PeriodicTaskService.

        Args:
            dao (PeriodicTaskDAO): PeriodicTaskDAO instance.
            redis_client (Redis): Redis async client instance.
        """
        self._dao = dao
        self._redis = redis_client

    def _validate_task_exists(self, task_name: str) -> None:
        """
        Validate that the task_name exists in Celery's task registry.

        Args:
            task_name (str): Full python module path of the task.

        Raises:
            HTTPException: If the task is not registered in Celery.
        """
        if task_name not in celery_app.tasks:
            log.warning("Validation failed: Task '%s' is not registered in Celery tasks.", task_name)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task '{task_name}' is not a registered Celery task",
            )

    async def _notify_schedule_changed(self) -> None:
        """Clear Redis cache and increment schedule version trigger using a Redis pipeline."""
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(CeleryRedisKeys.SCHEDULE_DATA.value)
            pipe.incr(CeleryRedisKeys.SCHEDULE_VERSION.value)
            await pipe.execute()
        log.info("PeriodicTaskService: Invalidated schedule cache and incremented version.")

    async def list_registered_celery_tasks(self) -> list[str]:
        """
        List all registered Celery task names available in the application.

        Returns:
            list[str]: Sorted list of registered Celery task names.
        """
        celery_app.loader.import_default_modules()
        return sorted([name for name in celery_app.tasks.keys() if not name.startswith("celery.")])

    async def list_tasks(self) -> list[PeriodicTaskResponse]:
        """
        Retrieve all periodic tasks.

        Returns:
            list[PeriodicTaskResponse]: List of periodic tasks.
        """
        return await self._dao.list_tasks()

    async def get_task(self, task_id: UUID) -> PeriodicTaskResponse:
        """
        Get a single periodic task by ID.

        Args:
            task_id (UUID): Unique task identifier.

        Returns:
            PeriodicTaskResponse: Details of the task.

        Raises:
            HTTPException: If task is not found.
        """
        task = await self._dao.get_task_by_id(task_id)
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Periodic task not found")
        return task

    async def create_task(self, task_in: PeriodicTaskCreate) -> PeriodicTaskResponse:
        """
        Create a new periodic task schedule entry. Multiple schedule entries can exist pointing to the same task.

        Args:
            task_in (PeriodicTaskCreate): Payload for task creation.

        Returns:
            PeriodicTaskResponse: The created periodic task model.

        Raises:
            HTTPException: If the task is invalid or a schedule entry with the same name already exists.
        """
        self._validate_task_exists(task_in.task)

        existing = await self._dao.get_task_by_name(task_in.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Periodic task with name '{task_in.name}' already exists",
            )

        task = await self._dao.create_task(task_in)
        await self._notify_schedule_changed()
        return task

    async def update_task(self, task_id: UUID, task_in: PeriodicTaskUpdate) -> PeriodicTaskResponse:
        """
        Update an existing periodic task schedule using COALESCE in DAO.

        Args:
            task_id (UUID): Task ID to update.
            task_in (PeriodicTaskUpdate): Partial fields to update.

        Returns:
            PeriodicTaskResponse: The updated periodic task model.

        Raises:
            HTTPException: If the periodic task is not found or task_name is invalid.
        """
        if task_in.task is not None:
            self._validate_task_exists(task_in.task)

        task = await self._dao.update_task(task_id, task_in)
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Periodic task not found")

        await self._notify_schedule_changed()
        return task

    async def delete_task(self, task_id: UUID) -> bool:
        """
        Delete a periodic task by ID.

        Args:
            task_id (UUID): Task ID to delete.

        Returns:
            bool: True if task was deleted successfully.

        Raises:
            HTTPException: If task was not found.
        """
        deleted = await self._dao.delete_task(task_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Periodic task not found")

        await self._notify_schedule_changed()
        return True

    async def trigger_task_manually(self, task_name: str, args: list, kwargs: dict) -> str:
        """
        Manually trigger any registered Celery task asynchronously on demand.

        Args:
            task_name (str): Full python path name of the Celery task.
            args (list): Positional arguments for the task.
            kwargs (dict): Keyword arguments for the task.

        Returns:
            str: Celery task execution ID string.

        Raises:
            HTTPException: If task does not exist or dispatch fails.
        """
        self._validate_task_exists(task_name)
        try:
            async_result = celery_app.send_task(task_name, args=args, kwargs=kwargs)
            log.info("PeriodicTaskService: Manually triggered task '%s' (Task ID: %s)", task_name, async_result.id)
            return str(async_result.id)
        except Exception as err:
            log.error("PeriodicTaskService: Failed to trigger task '%s': %s", task_name, err)
            raise


async def get_periodic_task_service(
    dao: PeriodicTaskDAO = Depends(get_periodic_task_dao),
    redis: Redis = Depends(get_redis),
) -> PeriodicTaskService:
    """
    Dependency provider for PeriodicTaskService.

    Args:
        dao (PeriodicTaskDAO): PeriodicTaskDAO instance from FastAPI dependency.
        redis (Redis): Redis client instance from FastAPI dependency.

    Returns:
        PeriodicTaskService: Initialized PeriodicTaskService instance.
    """
    return PeriodicTaskService(dao=dao, redis_client=redis)
