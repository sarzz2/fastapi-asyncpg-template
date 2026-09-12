import json
from uuid import UUID

from fastapi import Depends

from api.apps.common.constants import DLQConstants
from api.apps.common.v0.schemas.dead_letter_task import (
    DLQStatsResponse,
    DLQTaskFilter,
    DLQTaskResponse,
    DLQUpdatePayload,
)
from api.core.database import DataBase, get_db


class DeadLetterTaskDAO:
    """Data Access Object for Celery Dead Letter Queue database operations."""

    def __init__(self, db: DataBase) -> None:
        """
        Initialize DeadLetterTaskDAO.

        Args:
            db (DataBase): The database connection wrapper instance.
        """
        self.db = db

    async def list_tasks(
        self,
        filters: DLQTaskFilter,
        limit: int | None = 20,
        cursor: str | None = None,
        offset: int = 0,
    ) -> list[DLQTaskResponse]:
        """
        List DLQ tasks with cursor-based pagination or offset pagination and optional filtering.

        Args:
            filters (DLQTaskFilter): Query filter options.
            limit (int | None): Maximum number of items to return. If <= 0 or None, returns all matching.
            cursor (str | None): Cursor string (Task ID) for fetching next page.
            offset (int): Number of items to skip.

        Returns:
            list[DLQTaskResponse]: Matching DLQ task records.
        """
        conditions = ["1=1"]
        params: list[object] = []

        if filters.task_name:
            params.append(filters.task_name)
            conditions.append(f"task_name = ${len(params)}")

        if filters.exception_type:
            params.append(filters.exception_type)
            conditions.append(f"exception_type = ${len(params)}")

        if filters.search:
            params.append(f"%{filters.search}%")
            idx = len(params)
            conditions.append(f"(task_name ILIKE ${idx} OR exception_message ILIKE ${idx} OR traceback ILIKE ${idx})")

        if filters.date_from:
            params.append(filters.date_from)
            conditions.append(f"failed_at >= ${len(params)}")

        if filters.date_to:
            params.append(filters.date_to)
            conditions.append(f"failed_at <= ${len(params)}")

        if cursor:
            params.append(cursor)
            conditions.append(f"id < ${len(params)}::uuid")

        pagination_clauses: list[str] = []
        if limit is not None and limit > 0:
            params.append(limit)
            pagination_clauses.append(f"LIMIT ${len(params)}")

        if offset and offset > 0:
            params.append(offset)
            pagination_clauses.append(f"OFFSET ${len(params)}")

        query_parts = [
            "SELECT * FROM dead_letter_tasks",
            "WHERE " + " AND ".join(conditions),
            "ORDER BY id DESC",
        ]
        if pagination_clauses:
            query_parts.extend(pagination_clauses)
        data_query = "\n".join(query_parts)
        return await self.db.fetch(data_query, *params, model=DLQTaskResponse, fetch_row=False)

    async def count_tasks(self, filters: DLQTaskFilter) -> int:
        """
        Count total matching DLQ task records.

        Args:
            filters (DLQTaskFilter): Filter parameters.

        Returns:
            int: Total count of matching tasks.
        """
        conditions = ["1=1"]
        params: list[object] = []

        if filters.task_name:
            params.append(filters.task_name)
            conditions.append(f"task_name = ${len(params)}")

        if filters.exception_type:
            params.append(filters.exception_type)
            conditions.append(f"exception_type = ${len(params)}")

        if filters.search:
            params.append(f"%{filters.search}%")
            idx = len(params)
            conditions.append(f"(task_name ILIKE ${idx} OR exception_message ILIKE ${idx} OR traceback ILIKE ${idx})")

        if filters.date_from:
            params.append(filters.date_from)
            conditions.append(f"failed_at >= ${len(params)}")

        if filters.date_to:
            params.append(filters.date_to)
            conditions.append(f"failed_at <= ${len(params)}")

        count_parts = [
            "SELECT COUNT(*) FROM dead_letter_tasks",
            "WHERE " + " AND ".join(conditions),
        ]
        count_query = "\n".join(count_parts)
        count_row = await self.db.fetch(count_query, *params, fetch_row=True)
        return count_row["count"] if count_row and "count" in count_row else 0

    async def get_task_by_id(self, task_id: UUID) -> DLQTaskResponse | None:
        """Fetch a single DLQ task by UUID."""
        query = "SELECT * FROM dead_letter_tasks WHERE id = $1;"
        return await self.db.fetch(query, task_id, model=DLQTaskResponse, fetch_row=True)

    async def update_task_payload(
        self,
        payload: DLQUpdatePayload,
        task_id: UUID | None = None,
    ) -> int:
        """
        Update args, kwargs, or queue for single task (by task_id / task_ids) or bulk (by task_name).

        Args:
            payload (DLQUpdatePayload): Update specifications.
            task_id (UUID | None): Single task ID target if provided.

        Returns:
            int: Number of updated records count.
        """
        set_clauses: list[str] = ["updated_at = NOW()"]
        params: list[object] = []

        if payload.args is not None:
            args_val = json.dumps(payload.args) if isinstance(payload.args, (dict, list)) else payload.args
            params.append(args_val)
            set_clauses.append(f"args = ${len(params)}::jsonb")

        if payload.kwargs is not None:
            kwargs_val = json.dumps(payload.kwargs) if isinstance(payload.kwargs, (dict, list)) else payload.kwargs
            params.append(kwargs_val)
            idx = len(params)
            if payload.merge_kwargs and not task_id:
                set_clauses.append(f"kwargs = kwargs || ${idx}::jsonb")
            else:
                set_clauses.append(f"kwargs = ${idx}::jsonb")

        if payload.queue is not None:
            params.append(payload.queue)
            set_clauses.append(f"queue = ${len(params)}")

        ids = [task_id] if task_id else payload.task_ids
        where_clauses: list[str] = []

        if ids:
            params.append(ids)
            where_clauses.append(f"id = ANY(${len(params)}::uuid[])")
        elif payload.task_name:
            params.append(payload.task_name)
            where_clauses.append(f"task_name = ${len(params)}")
        else:
            where_clauses.append("1=1")

        update_parts = [
            "UPDATE dead_letter_tasks SET",
            ", ".join(set_clauses),
            "WHERE",
            " AND ".join(where_clauses),
        ]
        query = " ".join(update_parts)

        res = await self.db.execute(query, *params)
        try:
            return int(res.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0

    async def delete_tasks(
        self,
        task_ids: list[UUID] | None = None,
        task_name: str | None = None,
    ) -> int:
        """
        Delete DLQ tasks by IDs, task_name, or all tasks.

        Args:
            task_ids (list[UUID] | None): List of task IDs to delete.
            task_name (str | None): Task name to delete.

        Returns:
            int: Number of deleted tasks.
        """
        if task_ids:
            query = "DELETE FROM dead_letter_tasks WHERE id = ANY($1::uuid[]);"
            res = await self.db.execute(query, task_ids)
        elif task_name:
            query = "DELETE FROM dead_letter_tasks WHERE task_name = $1;"
            res = await self.db.execute(query, task_name)
        else:
            query = "DELETE FROM dead_letter_tasks;"
            res = await self.db.execute(query)

        try:
            return int(res.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0

    async def fetch_and_delete_tasks(
        self,
        task_ids: list[UUID] | None = None,
        task_name: str | None = None,
    ) -> list[DLQTaskResponse]:
        """
        Fetch task data and delete entries in a single atomic RETURNING step for retriggering.

        Args:
            task_ids (list[UUID] | None): List of task IDs to delete.
            task_name (str | None): Task name to delete.

        Returns:
            list[DLQTaskResponse]: List of deleted task records.
        """
        if task_ids:
            query = """
                DELETE FROM dead_letter_tasks
                WHERE id = ANY($1::uuid[])
                RETURNING *;
            """
            return await self.db.fetch(query, task_ids, model=DLQTaskResponse, fetch_row=False)
        if task_name:
            query = """
                DELETE FROM dead_letter_tasks
                WHERE task_name = $1
                RETURNING *;
            """
            return await self.db.fetch(query, task_name, model=DLQTaskResponse, fetch_row=False)
        query = """
            DELETE FROM dead_letter_tasks
            RETURNING *;
        """
        return await self.db.fetch(query, model=DLQTaskResponse, fetch_row=False)

    async def delete_old_tasks(self, days: int = DLQConstants.DEFAULT_RETENTION_DAYS) -> int:
        """
        Purge DLQ records older than the specified number of days.

        Args:
            days (int): Number of days to retain DLQ records.

        Returns:
            int: Number of deleted tasks.
        """
        query = "DELETE FROM dead_letter_tasks WHERE failed_at < NOW() - ($1 || ' days')::INTERVAL;"
        res = await self.db.execute(query, str(days))
        try:
            return int(res.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0

    async def get_statistics(self) -> DLQStatsResponse:
        """
        Compute aggregate statistics for DLQ tasks.

        Returns:
            DLQStatsResponse: Statistics summary model.
        """
        count_query = "SELECT COUNT(*) AS total_count FROM dead_letter_tasks;"
        counts = await self.db.fetch(count_query, fetch_row=True)
        total_count = counts["total_count"] if counts and "total_count" in counts else 0

        # By task_name
        task_query = """
            SELECT task_name, COUNT(*) as count
            FROM dead_letter_tasks
            GROUP BY task_name
            ORDER BY count DESC
            LIMIT 20;
        """
        task_rows = await self.db.fetch(task_query, fetch_row=False)
        by_task_name = {row["task_name"]: row["count"] for row in task_rows} if task_rows else {}

        # By exception_type
        exc_query = """
            SELECT COALESCE(exception_type, 'Unknown') as exception_type, COUNT(*) as count
            FROM dead_letter_tasks
            GROUP BY exception_type
            ORDER BY count DESC
            LIMIT 20;
        """
        exc_rows = await self.db.fetch(exc_query, fetch_row=False)
        by_exception_type = {row["exception_type"]: row["count"] for row in exc_rows} if exc_rows else {}

        return DLQStatsResponse(
            total_count=total_count,
            by_task_name=by_task_name,
            by_exception_type=by_exception_type,
        )


def get_dead_letter_task_dao(db: DataBase = Depends(get_db)) -> DeadLetterTaskDAO:
    """Dependency provider for DeadLetterTaskDAO."""
    return DeadLetterTaskDAO(db=db)
