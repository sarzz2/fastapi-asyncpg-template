"""
REST API endpoints for Celery Dead Letter Queue (DLQ) Management.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Security
from fastapi.responses import StreamingResponse

from api.apps.common.v0.schemas.dead_letter_task import (
    DLQActionResponse,
    DLQDeleteRequest,
    DLQRetriggerRequest,
    DLQStatsResponse,
    DLQTaskFilter,
    DLQTaskResponse,
    DLQUpdatePayload,
)
from api.apps.common.v0.service.dead_letter_task import DeadLetterTaskService, get_dead_letter_task_service
from api.apps.user.v0.schemas.user import UserData
from api.constants import ExportFormat
from api.core.dependencies import get_current_user
from api.utils.pagination import Page, PaginationParams, apply_cursor_pagination

router = APIRouter()


@router.get("", response_model=Page[DLQTaskResponse], summary="List Dead Letter Queue tasks")
async def list_dlq_tasks(
    pagination: Annotated[PaginationParams, Query()],
    filters: DLQTaskFilter = Depends(),
    service: DeadLetterTaskService = Depends(get_dead_letter_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["dlq:read"]),
) -> Page[DLQTaskResponse]:
    """
    Retrieve paginated Dead Letter Queue task entries with optional filtering using cursor pagination.

    Args:
        pagination (PaginationParams): Cursor pagination parameters (first, after).
        filters (DLQTaskFilter): Dependency injected query filter parameters.
        service (DeadLetterTaskService): DLQ service instance.

    Returns:
        Page[DLQTaskResponse]: Paginated DLQ task response model.
    """
    return await apply_cursor_pagination(
        fetch_func=service.list_tasks,
        params=pagination,
        get_cursor_value=lambda x: str(x.id),
        count_func=lambda: service.count_tasks(filters=filters),
        filters=filters,
    )


@router.get("/stats", response_model=DLQStatsResponse, summary="Get DLQ statistics and metrics")
async def get_dlq_stats(
    service: DeadLetterTaskService = Depends(get_dead_letter_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["dlq:read"]),
) -> DLQStatsResponse:
    """
    Retrieve summary metrics, top failing tasks, and exception statistics for the DLQ.

    Args:
        service (DeadLetterTaskService): DLQ service instance.

    Returns:
        DLQStatsResponse: DLQ statistics summary model.
    """
    return await service.get_stats()


@router.get("/export", summary="Export DLQ tasks to CSV or JSON")
async def export_dlq_tasks(
    export_format: str = Query(
        default=ExportFormat.CSV, pattern="^(csv|json)$", description="Export format: csv or json"
    ),
    filters: DLQTaskFilter = Depends(),
    service: DeadLetterTaskService = Depends(get_dead_letter_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["dlq:read"]),
) -> StreamingResponse:
    """
    Export filtered DLQ task entries as a downloadable file (CSV or JSON).

    Args:
        format (str): Export format ('csv' or 'json').
        filters (DLQTaskFilter): Filter query parameters dependency.
        service (DeadLetterTaskService): DLQ service instance.

    Returns:
        StreamingResponse: File stream download response.
    """
    return await service.export_tasks(filters=filters, export_format=export_format)


@router.get("/{task_id}", response_model=DLQTaskResponse, summary="Get single DLQ task by ID")
async def get_dlq_task(
    task_id: UUID,
    service: DeadLetterTaskService = Depends(get_dead_letter_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["dlq:read"]),
) -> DLQTaskResponse:
    """
    Get detailed information for a single DLQ task entry, including traceback.

    Args:
        task_id (UUID): DLQ task entry UUID.
        service (DeadLetterTaskService): DLQ service instance.

    Returns:
        DLQTaskResponse: Detailed DLQ task model.
    """
    return await service.get_task_by_id(task_id)


@router.patch("", response_model=DLQActionResponse, summary="Edit DLQ task payload(s)")
async def update_dlq_tasks(
    payload: DLQUpdatePayload,
    service: DeadLetterTaskService = Depends(get_dead_letter_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["dlq:update"]),
) -> DLQActionResponse:
    """
    Edit args, kwargs, or queue for DLQ tasks.
    If task_ids is passed, updates those specific tasks.
    If task_name is passed, updates all tasks for that task name.
    If neither is passed, updates all matching tasks.

    Args:
        payload (DLQUpdatePayload): Update specifications.
        service (DeadLetterTaskService): DLQ service instance.

    Returns:
        DLQActionResponse: Summary model of updated tasks count.
    """
    return await service.update_task_payload(payload=payload)


@router.post("/retrigger", response_model=DLQActionResponse, summary="Retrigger DLQ task(s)")
async def retrigger_dlq_tasks(
    request: DLQRetriggerRequest = DLQRetriggerRequest(),
    service: DeadLetterTaskService = Depends(get_dead_letter_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["dlq:retrigger"]),
) -> DLQActionResponse:
    """
    Retrigger DLQ tasks.
    If task_ids is passed, retriggers those specific tasks.
    If task_name is passed, retriggers all tasks for that task name.
    If neither is passed, retriggers all tasks.

    Args:
        request (DLQRetriggerRequest): Retrigger specifications.
        service (DeadLetterTaskService): DLQ service instance.

    Returns:
        DLQActionResponse: Summary model of retriggered tasks count.
    """
    return await service.retrigger_tasks(request=request)


@router.delete("", response_model=DLQActionResponse, summary="Delete DLQ tasks")
async def delete_dlq_tasks(
    request: DLQDeleteRequest | None = None,
    task_ids: list[UUID] | None = Query(default=None, description="Optional list of task UUIDs to delete"),
    service: DeadLetterTaskService = Depends(get_dead_letter_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["dlq:delete"]),
) -> DLQActionResponse:
    """
    Permanently delete DLQ entries.
    If task_ids is passed, deletes those specific tasks.
    If task_name is passed, deletes all tasks for that task name.
    If neither is passed, deletes all tasks.

    Args:
        request (DLQDeleteRequest | None): Delete request specifications body.
        task_ids (list[UUID] | None): Optional list of DLQ record UUIDs to delete via query params.
        service (DeadLetterTaskService): DLQ service instance.

    Returns:
        DLQActionResponse: Summary model of deleted task records.
    """
    return await service.delete_tasks(request=request, task_ids=task_ids)
