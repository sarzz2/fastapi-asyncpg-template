import json
from uuid import UUID

from fastapi import Depends

from api.apps.common.v0.schemas.periodic_task import PeriodicTaskCreate, PeriodicTaskResponse, PeriodicTaskUpdate
from api.core.database import DataBase, get_db


class PeriodicTaskDAO:
    """Data Access Object for periodic tasks database operations."""

    def __init__(self, db: DataBase) -> None:
        """
        Initialize PeriodicTaskDAO.

        Args:
            db (DataBase): The database connection wrapper instance.
        """
        self.db = db

    async def list_tasks(self) -> list[PeriodicTaskResponse]:
        """
        Fetch all periodic tasks from database as Pydantic models.

        Returns:
            list[PeriodicTaskResponse]: List of periodic task responses.
        """
        query = """
            SELECT * FROM periodic_tasks
            ORDER BY created_at DESC;
        """
        return await self.db.fetch(query, model=PeriodicTaskResponse, fetch_row=False)

    async def get_task_by_id(self, task_id: UUID) -> PeriodicTaskResponse | None:
        """
        Fetch a periodic task by UUID as a Pydantic model.

        Args:
            task_id (UUID): Unique identifier of the task.

        Returns:
            PeriodicTaskResponse | None: The task response object if found, else None.
        """
        query = """
            SELECT *
            FROM periodic_tasks
            WHERE id = $1;
        """
        return await self.db.fetch(query, task_id, model=PeriodicTaskResponse, fetch_row=True)

    async def get_task_by_name(self, name: str) -> PeriodicTaskResponse | None:
        """
        Fetch a periodic task by schedule name.

        Args:
            name (str): Unique schedule name identifier.

        Returns:
            PeriodicTaskResponse | None: The task response object if found, else None.
        """
        query = """
            SELECT * FROM periodic_tasks
            WHERE name = $1;
        """
        return await self.db.fetch(query, name, model=PeriodicTaskResponse, fetch_row=True)

    async def create_task(self, task_in: PeriodicTaskCreate) -> PeriodicTaskResponse:
        """
        Insert a new periodic task into the database.

        Args:
            task_in (PeriodicTaskCreate): Periodic task creation payload.

        Returns:
            PeriodicTaskResponse: The created periodic task model.
        """
        query = """
            INSERT INTO periodic_tasks (
                name, task, schedule_type, cron_minute, cron_hour, cron_day_of_week,
                cron_day_of_month, cron_month_of_year, interval_every, interval_period,
                args, kwargs, enabled
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12::jsonb, $13
            )
            RETURNING *;
        """
        schedule_type_val = task_in.schedule_type.value
        interval_period_val = task_in.interval_period.value if task_in.interval_period else None

        result = await self.db.fetch(
            query,
            task_in.name,
            task_in.task,
            schedule_type_val,
            task_in.cron_minute,
            task_in.cron_hour,
            task_in.cron_day_of_week,
            task_in.cron_day_of_month,
            task_in.cron_month_of_year,
            task_in.interval_every,
            interval_period_val,
            json.dumps(task_in.args),
            json.dumps(task_in.kwargs),
            task_in.enabled,
            model=PeriodicTaskResponse,
            fetch_row=True,
        )
        if result is None:
            raise RuntimeError("Failed to create periodic task record")
        return result

    async def update_task(self, task_id: UUID, task_in: PeriodicTaskUpdate) -> PeriodicTaskResponse | None:
        """
        Update an existing periodic task using SQL COALESCE for partial updates.

        Args:
            task_id (UUID): Unique identifier of task to update.
            task_in (PeriodicTaskUpdate): Fields to update.

        Returns:
            PeriodicTaskResponse | None: The updated periodic task model or None if not found.
        """
        query = """
            UPDATE periodic_tasks
            SET name = COALESCE($1, name),
                task = COALESCE($2, task),
                schedule_type = COALESCE($3, schedule_type),
                cron_minute = COALESCE($4, cron_minute),
                cron_hour = COALESCE($5, cron_hour),
                cron_day_of_week = COALESCE($6, cron_day_of_week),
                cron_day_of_month = COALESCE($7, cron_day_of_month),
                cron_month_of_year = COALESCE($8, cron_month_of_year),
                interval_every = COALESCE($9, interval_every),
                interval_period = COALESCE($10, interval_period),
                args = COALESCE($11::jsonb, args),
                kwargs = COALESCE($12::jsonb, kwargs),
                enabled = COALESCE($13, enabled),
                updated_at = NOW()
            WHERE id = $14
            RETURNING *;
        """
        schedule_type_val = task_in.schedule_type.value if task_in.schedule_type else None
        interval_period_val = task_in.interval_period.value if task_in.interval_period else None
        args_val = json.dumps(task_in.args) if task_in.args is not None else None
        kwargs_val = json.dumps(task_in.kwargs) if task_in.kwargs is not None else None

        return await self.db.fetch(
            query,
            task_in.name,
            task_in.task,
            schedule_type_val,
            task_in.cron_minute,
            task_in.cron_hour,
            task_in.cron_day_of_week,
            task_in.cron_day_of_month,
            task_in.cron_month_of_year,
            task_in.interval_every,
            interval_period_val,
            args_val,
            kwargs_val,
            task_in.enabled,
            task_id,
            model=PeriodicTaskResponse,
            fetch_row=True,
        )

    async def delete_task(self, task_id: UUID) -> bool:
        """
        Delete a periodic task by ID.

        Args:
            task_id (UUID): Task ID to delete.

        Returns:
            bool: True if task was deleted, False if task was not found.
        """
        query = "DELETE FROM periodic_tasks WHERE id = $1 RETURNING id;"
        row = await self.db.fetch(query, task_id, fetch_row=True)
        return bool(row)


def get_periodic_task_dao(db: DataBase = Depends(get_db)) -> PeriodicTaskDAO:
    """
    Dependency provider for PeriodicTaskDAO.

    Args:
        db (DataBase): Database instance from FastAPI dependency.

    Returns:
        PeriodicTaskDAO: Initialized PeriodicTaskDAO object.
    """
    return PeriodicTaskDAO(db=db)
