from uuid import UUID

from fastapi import APIRouter, Depends, Security, status

from api.apps.common.v0.schemas.periodic_task import (
    ManualTaskTriggerRequest,
    ManualTaskTriggerResponse,
    PeriodicTaskCreate,
    PeriodicTaskResponse,
    PeriodicTaskUpdate,
)
from api.apps.common.v0.service.periodic_task import PeriodicTaskService, get_periodic_task_service
from api.apps.user.v0.schemas.user import UserData
from api.core.dependencies import get_current_user

router = APIRouter()


@router.get("/registered-tasks", response_model=list[str], summary="List all registered Celery tasks")
async def list_registered_celery_tasks(
    service: PeriodicTaskService = Depends(get_periodic_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["periodic_tasks:read"]),
) -> list[str]:
    """Retrieve a list of all registered Celery task names in the application."""
    return await service.list_registered_celery_tasks()


@router.get("", response_model=list[PeriodicTaskResponse], summary="List all periodic tasks")
async def list_periodic_tasks(
    service: PeriodicTaskService = Depends(get_periodic_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["periodic_tasks:read"]),
) -> list[PeriodicTaskResponse]:
    """Retrieve all configured periodic tasks."""
    return await service.list_tasks()


@router.post(
    "",
    response_model=PeriodicTaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a periodic task schedule",
)
async def create_periodic_task(
    task_in: PeriodicTaskCreate,
    service: PeriodicTaskService = Depends(get_periodic_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["periodic_tasks:create"]),
) -> PeriodicTaskResponse:
    """Create a new dynamic periodic task schedule."""
    return await service.create_task(task_in)


@router.get("/{task_id}", response_model=PeriodicTaskResponse, summary="Get periodic task by ID")
async def get_periodic_task(
    task_id: UUID,
    service: PeriodicTaskService = Depends(get_periodic_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["periodic_tasks:read"]),
) -> PeriodicTaskResponse:
    """Get details of a specific periodic task by ID."""
    return await service.get_task(task_id)


@router.put("/{task_id}", response_model=PeriodicTaskResponse, summary="Update periodic task")
async def update_periodic_task(
    task_id: UUID,
    task_in: PeriodicTaskUpdate,
    service: PeriodicTaskService = Depends(get_periodic_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["periodic_tasks:update"]),
) -> PeriodicTaskResponse:
    """Update an existing periodic task schedule."""
    return await service.update_task(task_id, task_in)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete periodic task")
async def delete_periodic_task(
    task_id: UUID,
    service: PeriodicTaskService = Depends(get_periodic_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["periodic_tasks:delete"]),
) -> None:
    """Delete a periodic task schedule by ID."""
    await service.delete_task(task_id)


@router.post(
    "/{task_id}/trigger",
    response_model=ManualTaskTriggerResponse,
    summary="Trigger a configured periodic task manually",
)
async def trigger_periodic_task_manually(
    task_id: UUID,
    service: PeriodicTaskService = Depends(get_periodic_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["periodic_tasks:trigger"]),
) -> ManualTaskTriggerResponse:
    """Manually trigger a configured periodic task immediately on demand."""
    task_detail = await service.get_task(task_id)
    celery_task_id = await service.trigger_task_manually(
        task_name=task_detail.task,
        args=task_detail.args,
        kwargs=task_detail.kwargs,
    )
    return ManualTaskTriggerResponse(
        message=f"Task '{task_detail.name}' dispatched successfully",
        task_id=celery_task_id,
        task_name=task_detail.task,
    )


@router.post(
    "/trigger-by-name",
    response_model=ManualTaskTriggerResponse,
    summary="Trigger any task manually by name",
)
async def trigger_task_by_name(
    request: ManualTaskTriggerRequest,
    service: PeriodicTaskService = Depends(get_periodic_task_service),
    _current_user: UserData = Security(get_current_user, scopes=["periodic_tasks:trigger"]),
) -> ManualTaskTriggerResponse:
    """Manually trigger any registered Celery task by full python path name."""
    celery_task_id = await service.trigger_task_manually(
        task_name=request.task_name,
        args=request.args,
        kwargs=request.kwargs,
    )
    return ManualTaskTriggerResponse(
        message=f"Task '{request.task_name}' dispatched successfully",
        task_id=celery_task_id,
        task_name=request.task_name,
    )
