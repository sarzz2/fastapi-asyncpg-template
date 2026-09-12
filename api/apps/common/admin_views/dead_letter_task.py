"""
Admin views for Dead Letter Queue management.
"""

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette_admin import action, flash, row_action
from starlette_admin.exceptions import ActionFailed
from starlette_admin.fields import DateTimeField, IntegerField, JSONField, StringField, TextAreaField, UUIDField
from starlette_admin.filters import FilterGroup

from api.apps.common.v0.dao.dead_letter_task import DeadLetterTaskDAO
from api.apps.common.v0.schemas.dead_letter_task import (
    DLQRetriggerRequest,
    DLQTaskFilter,
    DLQTaskResponse,
    DLQUpdatePayload,
)
from api.apps.common.v0.service.dead_letter_task import DeadLetterTaskService
from api.core.database import DataBase
from api.utils.admin_view import BaseAppAdminView


class DeadLetterTaskAdminView(BaseAppAdminView):
    """
    Custom Starlette-Admin view for inspecting, editing payloads, and retriggering DLQ tasks.
    """

    key = "dead_letter_task"
    identity = "dead_letter_task"
    name = "Dead Letter Task"
    label = "Dead Letter Queue"
    menu_label = "Dead Letter Queue"
    icon = "fa-solid fa-triangle-exclamation"
    pk_attr = "id"

    fields = [
        UUIDField("id", label="ID", read_only=True),
        StringField("task_id", label="Celery Task ID", read_only=True),
        StringField("task_name", label="Task Name", required=True),
        StringField("queue", label="Queue"),
        JSONField("args", label="Arguments (JSON)"),
        JSONField("kwargs", label="Keyword Arguments (JSON)"),
        StringField("exception_type", label="Exception Type", read_only=True),
        StringField("exception_message", label="Exception Message", read_only=True),
        TextAreaField("traceback", label="Traceback", read_only=True),
        IntegerField("retry_count", label="Retry Count", read_only=True),
        DateTimeField("failed_at", label="Failed At", read_only=True),
    ]

    def can_create(self, request: Request) -> bool:
        """Disable creation of Dead Letter Queue tasks from admin UI."""
        return False

    def can_edit(self, request: Request) -> bool:
        """Allow editing Dead Letter Queue task payloads."""
        return True

    def can_delete(self, request: Request) -> bool:
        """Allow deleting Dead Letter Queue tasks."""
        return True

    def __init__(self, db: DataBase) -> None:
        """
        Initialize DeadLetterTaskAdminView with DeadLetterTaskDAO.

        Args:
            db (DataBase): Database connection instance.
        """
        super().__init__()
        self.db = db
        self.dao = DeadLetterTaskDAO(self.db)

    @staticmethod
    def _to_admin_object(task: DLQTaskResponse) -> SimpleNamespace:
        """
        Convert DLQTaskResponse Pydantic model into a Starlette-Admin compatible object.

        Args:
            task (DLQTaskResponse): DLQTaskResponse Pydantic model instance.

        Returns:
            SimpleNamespace: Admin-compatible object with dynamically mapped fields.
        """
        return SimpleNamespace(**task.model_dump())

    async def get_pk_value(self, request: Request, obj: Any) -> Any:
        """
        Extract primary key (ID) from DLQ task object or dictionary.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            obj (Any): The DLQ task data object or dictionary.

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
        Find all records matching criteria.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            skip (int): Number of records to skip for pagination. Defaults to 0.
            limit (int): Maximum number of records to return. Defaults to 100.
            q (str | None): Optional search query string. Defaults to None.
            sorts (Sequence[tuple[str, str]] | None): Sort fields and directions. Defaults to None.
            filters (FilterGroup | None): Applied filter conditions. Defaults to None.

        Returns:
            Sequence[Any]: List of matching DLQ task objects.
        """
        filter_opts = DLQTaskFilter(search=q)
        actual_limit = limit if limit > 0 else None
        tasks = await self.dao.list_tasks(filters=filter_opts, limit=actual_limit, offset=skip)
        return [self._to_admin_object(t) for t in tasks]

    async def count(
        self,
        request: Request,
        q: str | None = None,
        filters: FilterGroup | None = None,
    ) -> int:
        """
        Count total records matching criteria.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            q (str | None): Optional search query string. Defaults to None.
            filters (FilterGroup | None): Applied filter conditions. Defaults to None.

        Returns:
            int: Total count of DLQ task records.
        """
        filter_opts = DLQTaskFilter(search=q)
        return await self.dao.count_tasks(filters=filter_opts)

    async def find_by_pk(self, request: Request, pk: Any) -> Any | None:
        """
        Find a single DLQ task by primary key.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (Any): Primary key of the DLQ task.

        Returns:
            Any | None: DLQ task data object if found, None otherwise.
        """
        try:
            task = await self.dao.get_task_by_id(UUID(str(pk)))
            return self._to_admin_object(task) if task else None
        except (ValueError, TypeError):
            return None

    async def find_by_pks(self, request: Request, pks: list[Any]) -> Sequence[Any]:
        """
        Find multiple DLQ tasks by primary keys.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of primary keys (UUIDs or strings).

        Returns:
            Sequence[Any]: List of matching DLQ task objects.
        """
        if not pks:
            return []
        task_list: list[Any] = []
        for pk in pks:
            obj = await self.find_by_pk(request, pk)
            if obj is not None:
                task_list.append(obj)
        return task_list

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        """
        Create is disabled for Dead Letter Queue tasks.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            data (dict[str, Any]): Input record payload dictionary.

        Raises:
            NotImplementedError: Always, as DLQ entries can only be generated by failed tasks.
        """
        raise NotImplementedError("Manual creation of Dead Letter Queue tasks is not permitted.")

    async def repr(self, obj: Any, request: Request) -> str:
        """
        Return human-readable representation of DLQ task for toast and flash messages.

        Args:
            obj (Any): The domain object or dictionary.
            request (Request): The incoming Starlette/FastAPI HTTP request.

        Returns:
            str: Human-readable display string.
        """
        task_name = getattr(obj, "task_name", None) or (obj.get("task_name") if isinstance(obj, dict) else None)
        pk = await self.get_pk_value(request, obj)
        if task_name:
            return f"{task_name} ({pk})"
        return f"DLQ Task ({pk})"

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        """
        Edit an existing DLQ task's payload args, kwargs, or queue.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (Any): Primary key of target task.
            data (dict[str, Any]): Dictionary containing field updates.

        Returns:
            Any: Updated DLQ task data object.
        """
        task_id = UUID(str(pk))
        payload = DLQUpdatePayload(
            args=data.get("args"),
            kwargs=data.get("kwargs"),
            queue=data.get("queue"),
        )
        count = await self.dao.update_task_payload(payload=payload, task_id=task_id)
        if count == 0:
            raise ValueError(f"DLQ task with ID '{pk}' not found.")
        return await self.find_by_pk(request, pk)

    async def delete(self, request: Request, pks: list[Any]) -> int:
        """
        Delete DLQ tasks by primary keys.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of primary keys to delete.

        Returns:
            int: Number of deleted tasks.
        """
        task_uuids = [UUID(str(pk)) for pk in pks]
        return await self.dao.delete_tasks(task_uuids)

    @action(
        name="retrigger_selected",
        text="🔄 Retrigger Selected Tasks",
        confirmation="Are you sure you want to retrigger the selected DLQ tasks?",
        submit_btn_text="Retrigger Tasks",
    )
    async def retrigger_selected_action(self, request: Request, pks: list[Any]) -> str:
        """
        Batch action to retrigger selected DLQ tasks directly.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of primary keys of tasks to retrigger.

        Returns:
            str: Flash summary message with count of retriggered tasks.
        """
        task_uuids = [UUID(str(pk)) for pk in pks]
        service = DeadLetterTaskService(dao=self.dao)
        res = await service.retrigger_tasks(DLQRetriggerRequest(task_ids=task_uuids))
        flash(request, res.message, "success")
        return res.message

    @row_action(
        name="retrigger_single",
        text="🔄 Retrigger Task",
        icon_class="fa-solid fa-rotate-right",
    )
    async def retrigger_single_row_action(self, request: Request, pk: Any) -> str:
        """
        Row action to retrigger a single DLQ task immediately.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (Any): Primary key of target task.

        Returns:
            str: Flash message indicating new Celery task ID.
        """
        try:
            task_uuid = UUID(str(pk))
            service = DeadLetterTaskService(dao=self.dao)
            res = await service.retrigger_tasks(task_id=task_uuid)
            flash(request, res.message, "success")
            return res.message
        except Exception as exc:
            flash(request, f"Failed to retrigger task: {exc}", "danger")
            raise ActionFailed(str(exc)) from exc
