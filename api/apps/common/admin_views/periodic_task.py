"""
Admin views for Periodic Tasks management.
"""

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette_admin import action, row_action
from starlette_admin.fields import (
    BooleanField,
    DateTimeField,
    EnumField,
    IntegerField,
    JSONField,
    StringField,
    UUIDField,
)
from starlette_admin.filters import FilterGroup

from api.apps.common.constants import IntervalPeriod, ScheduleType
from api.apps.common.v0.dao.periodic_task import PeriodicTaskDAO
from api.apps.common.v0.schemas.periodic_task import PeriodicTaskCreate, PeriodicTaskResponse, PeriodicTaskUpdate
from api.core.celery_app import celery_app
from api.core.database import DataBase
from api.utils.admin_view import BaseAppAdminView


class PeriodicTaskAdminView(BaseAppAdminView):
    """
    Custom Starlette-Admin view for managing Periodic Tasks and manually triggering tasks.
    """

    key = "periodic_task"
    identity = "periodic_task"
    name = "Periodic Task"
    label = "Periodic Tasks"
    menu_label = "Periodic Tasks"
    icon = "fa-solid fa-clock"
    pk_attr = "id"

    fields = [
        UUIDField("id", label="ID", read_only=True),
        StringField("name", label="Schedule Name", required=True),
        StringField("task", label="Celery Task Path", required=True),
        EnumField("schedule_type", label="Schedule Type", enum=ScheduleType, required=True),
        StringField("cron_minute", label="Cron Minute"),
        StringField("cron_hour", label="Cron Hour"),
        StringField("cron_day_of_week", label="Cron Day of Week"),
        StringField("cron_day_of_month", label="Cron Day of Month"),
        StringField("cron_month_of_year", label="Cron Month of Year"),
        IntegerField("interval_every", label="Interval Every"),
        EnumField("interval_period", label="Interval Period", enum=IntervalPeriod),
        JSONField("args", label="Arguments (JSON)"),
        JSONField("kwargs", label="Keyword Arguments (JSON)"),
        BooleanField("enabled", label="Enabled"),
        DateTimeField("created_at", label="Created At", read_only=True),
        DateTimeField("updated_at", label="Updated At", read_only=True),
    ]

    def __init__(self, db: DataBase) -> None:
        """
        Initialize PeriodicTaskAdminView with PeriodicTaskDAO.

        Args:
            db (DataBase): Database connection instance.
        """
        super().__init__()
        self.db = db
        self.dao = PeriodicTaskDAO(self.db)

    @staticmethod
    def _to_admin_object(task: PeriodicTaskResponse) -> SimpleNamespace:
        """
        Convert PeriodicTaskResponse Pydantic model into a Starlette-Admin compatible object.

        Args:
            task (PeriodicTaskResponse): PeriodicTaskResponse Pydantic model instance.

        Returns:
            SimpleNamespace: Admin-compatible object with dynamically mapped fields.
        """
        return SimpleNamespace(**task.model_dump())

    async def get_pk_value(self, request: Request, obj: Any) -> Any:
        """
        Extract primary key (ID) from periodic task object or dictionary.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            obj (Any): The periodic task data object or dictionary.

        Returns:
            Any: The primary key (ID) value.
        """
        if isinstance(obj, dict):
            return obj.get("id")
        return getattr(obj, "id", None)

    async def find_all(
        self,
        request: Request,
        skip: int = 0,
        limit: int = 100,
        q: str | None = None,
        sorts: Sequence[tuple[str, str]] | None = None,
        filters: FilterGroup | None = None,
    ) -> Sequence[Any]:
        """
        Retrieve paginated list of periodic tasks.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            skip (int): Number of records to skip for pagination. Defaults to 0.
            limit (int): Maximum number of records to return. Defaults to 100.
            q (str | None): Optional search query string. Defaults to None.
            sorts (Sequence[tuple[str, str]] | None): Sort fields and directions. Defaults to None.
            filters (FilterGroup | None): Applied filter conditions. Defaults to None.

        Returns:
            Sequence[Any]: List of periodic task objects.
        """
        tasks = await self.dao.list_tasks()
        return [self._to_admin_object(task) for task in tasks[skip : skip + limit]]

    async def count(
        self,
        request: Request,
        q: str | None = None,
        filters: FilterGroup | None = None,
    ) -> int:
        """
        Count total number of periodic task records in database.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            q (str | None): Optional search query string. Defaults to None.
            filters (FilterGroup | None): Applied filter conditions. Defaults to None.

        Returns:
            int: Total count of periodic task records.
        """
        record = await self.db.fetch("SELECT COUNT(*) as cnt FROM periodic_tasks", fetch_row=True)
        return int(record["cnt"]) if record else 0

    async def find_by_pk(self, request: Request, pk: UUID | str) -> Any | None:
        """
        Find a single periodic task by primary key.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (UUID | str): Primary key (UUID or string) of the periodic task.

        Returns:
            Any | None: Periodic task data object if found, None otherwise.
        """
        task_id = UUID(str(pk))
        task = await self.dao.get_task_by_id(task_id)
        if not task:
            return None
        return self._to_admin_object(task)

    async def find_by_pks(self, request: Request, pks: list[Any]) -> Sequence[Any]:
        """
        Find multiple periodic tasks by primary keys.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of primary keys (UUIDs or strings).

        Returns:
            Sequence[Any]: List of matching periodic task objects.
        """
        if not pks:
            return []
        tasks = []
        for pk in pks:
            task_id = UUID(str(pk))
            t = await self.dao.get_task_by_id(task_id)
            if t:
                tasks.append(self._to_admin_object(t))
        return tasks

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        """
        Create a new periodic task schedule.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            data (dict[str, Any]): Dictionary of field values submitted from form.

        Returns:
            Any: Created periodic task object.
        """
        task_create = PeriodicTaskCreate(
            name=data["name"],
            task=data["task"],
            schedule_type=data["schedule_type"],
            cron_minute=data.get("cron_minute") or "*",
            cron_hour=data.get("cron_hour") or "*",
            cron_day_of_week=data.get("cron_day_of_week") or "*",
            cron_day_of_month=data.get("cron_day_of_month") or "*",
            cron_month_of_year=data.get("cron_month_of_year") or "*",
            interval_every=data.get("interval_every"),
            interval_period=data.get("interval_period"),
            args=data.get("args") or [],
            kwargs=data.get("kwargs") or {},
            enabled=data.get("enabled", True),
        )
        task = await self.dao.create_task(task_create)
        return self._to_admin_object(task)

    async def edit(self, request: Request, pk: UUID | str, data: dict[str, Any]) -> Any:
        """
        Update an existing periodic task schedule.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (UUID | str): Primary key (UUID or string) of task to update.
            data (dict[str, Any]): Updated field values submitted from form.

        Returns:
            Any: Updated periodic task object.

        Raises:
            ValueError: If target periodic task is not found.
        """
        task_id = UUID(str(pk))
        task_update = PeriodicTaskUpdate(
            name=data.get("name"),
            task=data.get("task"),
            schedule_type=data.get("schedule_type"),
            cron_minute=data.get("cron_minute"),
            cron_hour=data.get("cron_hour"),
            cron_day_of_week=data.get("cron_day_of_week"),
            cron_day_of_month=data.get("cron_day_of_month"),
            cron_month_of_year=data.get("cron_month_of_year"),
            interval_every=data.get("interval_every"),
            interval_period=data.get("interval_period"),
            args=data.get("args"),
            kwargs=data.get("kwargs"),
            enabled=data.get("enabled"),
        )
        task = await self.dao.update_task(task_id, task_update)
        if not task:
            raise ValueError(f"Periodic task with ID {pk} not found")
        return self._to_admin_object(task)

    async def delete(self, request: Request, pks: list[Any]) -> int:
        """
        Delete periodic task schedules by primary keys.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of primary keys of tasks to delete.

        Returns:
            int: Number of deleted periodic task records.
        """
        count_deleted = 0
        for pk in pks:
            task_id = UUID(str(pk))
            deleted = await self.dao.delete_task(task_id)
            if deleted:
                count_deleted += 1
        return count_deleted

    @row_action(
        name="trigger_now",
        text="Trigger Now",
        icon_class="fa-solid fa-play",
        confirmation="Are you sure you want to trigger this Celery task immediately?",
    )
    async def trigger_now_action(self, _request: Request, pk: Any) -> str:
        """
        Row action to manually trigger a Celery task immediately on demand.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (Any): Primary key of target periodic task.

        Returns:
            str: Flash message indicating task dispatch and Celery task execution ID.

        Raises:
            ValueError: If target task is not found.
        """
        task_id = UUID(str(pk))
        task = await self.dao.get_task_by_id(task_id)
        if not task:
            raise ValueError("Periodic task not found")

        result = celery_app.send_task(task.task, args=task.args, kwargs=task.kwargs)
        return f"Task '{task.name}' ({task.task}) triggered successfully. Celery Task ID: {result.id}"

    @row_action(
        name="toggle_enabled",
        text="Toggle Enabled",
        icon_class="fa-solid fa-power-off",
    )
    async def toggle_enabled_action(self, _request: Request, pk: Any) -> str:
        """
        Row action to toggle a periodic task's enabled/disabled schedule state.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (Any): Primary key of target periodic task.

        Returns:
            str: Flash message with updated schedule state.

        Raises:
            ValueError: If target task is not found.
        """
        task_id = UUID(str(pk))
        task = await self.dao.get_task_by_id(task_id)
        if not task:
            raise ValueError("Periodic task not found")

        new_enabled = not task.enabled
        await self.dao.update_task(task_id, PeriodicTaskUpdate(enabled=new_enabled))
        state_text = "enabled" if new_enabled else "disabled"
        return f"Periodic task '{task.name}' is now {state_text}."

    @action(
        name="enable_selected",
        text="Enable Selected Tasks",
        icon_class="fa-solid fa-circle-check",
        confirmation="Enable selected task schedules?",
    )
    async def enable_selected_action(self, _request: Request, pks: list[Any]) -> str:
        """
        Batch action to enable selected task schedules.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of primary keys of tasks to enable.

        Returns:
            str: Flash summary message with count of enabled tasks.
        """
        count = 0
        for pk in pks:
            task_id = UUID(str(pk))
            await self.dao.update_task(task_id, PeriodicTaskUpdate(enabled=True))
            count += 1
        return f"Successfully enabled {count} periodic tasks."

    @action(
        name="disable_selected",
        text="Disable Selected Tasks",
        icon_class="fa-solid fa-circle-stop",
        confirmation="Disable selected task schedules?",
    )
    async def disable_selected_action(self, _request: Request, pks: list[Any]) -> str:
        """
        Batch action to disable selected task schedules.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of primary keys of tasks to disable.

        Returns:
            str: Flash summary message with count of disabled tasks.
        """
        count = 0
        for pk in pks:
            task_id = UUID(str(pk))
            await self.dao.update_task(task_id, PeriodicTaskUpdate(enabled=False))
            count += 1
        return f"Successfully disabled {count} periodic tasks."
