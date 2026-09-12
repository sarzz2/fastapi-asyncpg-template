"""
Service layer for Dead Letter Queue operations.
"""

import csv
import io
import json
import logging
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from api.apps.common.v0.dao.dead_letter_task import DeadLetterTaskDAO, get_dead_letter_task_dao
from api.apps.common.v0.schemas.dead_letter_task import (
    DLQActionResponse,
    DLQDeleteRequest,
    DLQRetriggerRequest,
    DLQStatsResponse,
    DLQTaskFilter,
    DLQTaskResponse,
    DLQUpdatePayload,
)
from api.constants import ExportFormat
from api.core.celery_app import celery_app

log = logging.getLogger(__name__)


class DeadLetterTaskService:
    """Service layer managing Dead Letter Queue operations, editing, retriggering, and batching."""

    def __init__(self, dao: DeadLetterTaskDAO) -> None:
        """
        Initialize DeadLetterTaskService.

        Args:
            dao (DeadLetterTaskDAO): Data access object for DLQ database operations.
        """
        self.dao = dao

    async def list_tasks(
        self,
        filters: DLQTaskFilter,
        limit: int = 20,
        cursor: str | None = None,
    ) -> list[DLQTaskResponse]:
        """
        List DLQ tasks with cursor-based pagination and filters.

        Args:
            filters (DLQTaskFilter): Applied query filter options.
            limit (int): Maximum items limit. Defaults to 20.
            cursor (str | None): Cursor string (Task ID) for fetching next page.

        Returns:
            list[DLQTaskResponse]: List of DLQ task records.
        """
        return await self.dao.list_tasks(filters=filters, limit=limit, cursor=cursor)

    async def count_tasks(self, filters: DLQTaskFilter) -> int:
        """
        Count total matching DLQ task records.

        Args:
            filters (DLQTaskFilter): Filter parameters.

        Returns:
            int: Total count of matching tasks.
        """
        return await self.dao.count_tasks(filters=filters)

    async def get_task_by_id(self, task_id: UUID) -> DLQTaskResponse:
        """
        Fetch DLQ task by ID or raise 404.

        Args:
            task_id (UUID): Unique DLQ entry identifier.

        Returns:
            DLQTaskResponse: DLQ task detail model.
        """
        task = await self.dao.get_task_by_id(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dead letter task with ID '{task_id}' not found.",
            )
        return task

    async def update_task_payload(
        self,
        payload: DLQUpdatePayload,
        task_id: UUID | None = None,
    ) -> DLQActionResponse:
        """
        Update single or multiple task payloads (args, kwargs, queue).

        Args:
            payload (DLQUpdatePayload): Field payload modifications.
            task_id (UUID | None): Target task UUID if updating a single task.

        Returns:
            DLQActionResponse: Summary model of updated records.
        """
        count = await self.dao.update_task_payload(payload=payload, task_id=task_id)
        return DLQActionResponse(
            message=f"Successfully updated {count} task(s).",
            affected_count=count,
        )

    async def retrigger_tasks(
        self,
        request: DLQRetriggerRequest | None = None,
        task_id: UUID | None = None,
    ) -> DLQActionResponse:
        """
        Retrigger single or bulk tasks from DLQ.

        Fetches task details, deletes original DLQ entries, and enqueues tasks to Celery.

        Args:
            request (DLQRetriggerRequest | None): Retrigger specification model.
            task_id (UUID | None): Target task UUID if retriggering a single task.

        Returns:
            DLQActionResponse: Summary of retriggered count.
        """
        task_ids = [task_id] if task_id else (request.task_ids if request else None)
        task_name = request.task_name if request else None

        tasks = await self.dao.fetch_and_delete_tasks(
            task_ids=task_ids,
            task_name=task_name,
        )
        if not tasks:
            if task_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Dead letter task with ID '{task_id}' not found or already deleted.",
                )
            return DLQActionResponse(
                message="No matching tasks found to retrigger",
                affected_count=0,
            )

        retriggered_count = 0
        for dlq_task in tasks:
            try:
                celery_app.send_task(
                    dlq_task.task_name,
                    args=dlq_task.args,
                    kwargs=dlq_task.kwargs,
                    queue=dlq_task.queue,
                )
                retriggered_count += 1
            except Exception as exc:  # pylint: disable=broad-except
                log.error("Failed to send retrigger task %s: %s", dlq_task.id, exc)
                raise

        return DLQActionResponse(
            message=f"Successfully retriggered {retriggered_count} task(s).",
            affected_count=retriggered_count,
        )

    async def delete_tasks(
        self,
        request: DLQDeleteRequest | None = None,
        task_id: UUID | None = None,
        task_ids: list[UUID] | None = None,
    ) -> DLQActionResponse:
        """
        Delete single or multiple DLQ tasks permanently by IDs or matching filters.

        Args:
            request (DLQDeleteRequest | None): Delete request specification.
            task_id (UUID | None): Single task UUID to delete.
            task_ids (list[UUID] | None): Specific task UUIDs list to delete.

        Returns:
            DLQActionResponse: Summary model of deleted task records count.
        """
        ids = [task_id] if task_id else (task_ids or (request.task_ids if request else None))
        task_name = request.task_name if request else None

        count = await self.dao.delete_tasks(
            task_ids=ids,
            task_name=task_name,
        )
        return DLQActionResponse(
            message=f"Successfully deleted {count} task record(s).",
            affected_count=count,
        )

    async def get_stats(self) -> DLQStatsResponse:
        """
        Get summary statistics of Dead Letter Queue.

        Returns:
            DLQStatsResponse: Statistics summary model.
        """
        return await self.dao.get_statistics()

    async def export_tasks(
        self,
        filters: DLQTaskFilter,
        export_format: str = ExportFormat.JSON,
    ) -> StreamingResponse:
        """
        Export matching DLQ entries as CSV or JSON file stream.

        Args:
            filters (DLQTaskFilter): Filter parameters.
            export_format (str): Desired export format ('csv' or 'json').

        Returns:
            StreamingResponse: Downloadable stream.
        """
        tasks = await self.dao.list_tasks(filters=filters, limit=5000)

        if export_format.lower() == ExportFormat.CSV:
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "ID",
                    "Celery Task ID",
                    "Task Name",
                    "Queue",
                    "Exception Type",
                    "Exception Message",
                    "Retry Count",
                    "Failed At",
                ]
            )
            for t in tasks:
                writer.writerow(
                    [
                        str(t.id),
                        t.task_id,
                        t.task_name,
                        t.queue,
                        t.exception_type,
                        t.exception_message,
                        t.retry_count,
                        t.failed_at.isoformat(),
                    ]
                )
            output.seek(0)
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode("utf-8")),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=dlq_export.csv"},
            )

        json_content = json.dumps([t.model_dump(mode="json") for t in tasks], indent=2)
        return StreamingResponse(
            io.BytesIO(json_content.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=dlq_export.json"},
        )


def get_dead_letter_task_service(
    dao: DeadLetterTaskDAO = Depends(get_dead_letter_task_dao),
) -> DeadLetterTaskService:
    """Dependency provider for DeadLetterTaskService."""
    return DeadLetterTaskService(dao=dao)
