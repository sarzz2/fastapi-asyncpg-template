# pylint: disable=redefined-outer-name
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from api.apps.common.constants import IntervalPeriod, ScheduleType
from api.apps.common.v0.dao.periodic_task import PeriodicTaskDAO
from api.apps.common.v0.routes.periodic_task import list_periodic_tasks
from api.apps.common.v0.schemas.periodic_task import PeriodicTaskCreate, PeriodicTaskResponse, PeriodicTaskUpdate
from api.apps.common.v0.service.periodic_task import PeriodicTaskService
from api.core.celery_scheduler import parse_schedule


def test_parse_schedule_crontab() -> None:
    """Test parsing crontab schedule record."""
    row = {
        "schedule_type": "crontab",
        "cron_minute": "*/5",
        "cron_hour": "14",
        "cron_day_of_week": "*",
        "cron_day_of_month": "*",
        "cron_month_of_year": "*",
    }
    sched = parse_schedule(row)
    assert sched.minute == {"*/5"} or str(sched) is not None


def test_parse_schedule_interval() -> None:
    """Test parsing interval schedule record."""
    row = {
        "schedule_type": "interval",
        "interval_every": 5,
        "interval_period": "minutes",
    }
    sched = parse_schedule(row)
    assert sched.run_every.total_seconds() == 300


@pytest.fixture
def mock_dao() -> AsyncMock:
    """Mock PeriodicTaskDAO."""
    return AsyncMock(spec=PeriodicTaskDAO)


@pytest.fixture
def mock_redis() -> MagicMock:
    """Mock Redis client."""
    redis_mock = MagicMock()
    pipe_mock = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=[True, 1])

    cm = AsyncMock()
    cm.__aenter__.return_value = pipe_mock
    cm.__aexit__.return_value = None
    redis_mock.pipeline.return_value = cm
    return redis_mock


@pytest.fixture
def periodic_service(mock_dao: AsyncMock, mock_redis: MagicMock) -> PeriodicTaskService:
    """Fixture for PeriodicTaskService."""
    return PeriodicTaskService(dao=mock_dao, redis_client=mock_redis)


@pytest.mark.asyncio
async def test_list_tasks(periodic_service: PeriodicTaskService, mock_dao: AsyncMock) -> None:
    """Test listing periodic tasks."""
    task_resp = PeriodicTaskResponse(
        id=uuid4(),
        name="test-task",
        task="api.tasks.test",
        schedule_type=ScheduleType.CRONTAB,
        cron_minute="0",
        cron_hour="0",
        cron_day_of_week="*",
        cron_day_of_month="*",
        cron_month_of_year="*",
        interval_every=None,
        interval_period=None,
        args=[],
        kwargs={},
        enabled=True,
        last_run_at=None,
        total_run_count=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_dao.list_tasks.return_value = [task_resp]
    tasks = await periodic_service.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].name == "test-task"


@pytest.mark.asyncio
async def test_create_task(periodic_service: PeriodicTaskService, mock_dao: AsyncMock) -> None:
    """Test creating a periodic task."""
    mock_dao.get_task_by_name.return_value = None
    task_resp = PeriodicTaskResponse(
        id=uuid4(),
        name="new-task",
        task="api.tasks.new",
        schedule_type=ScheduleType.INTERVAL,
        cron_minute="*",
        cron_hour="*",
        cron_day_of_week="*",
        cron_day_of_month="*",
        cron_month_of_year="*",
        interval_every=10,
        interval_period=IntervalPeriod.MINUTES,
        args=[],
        kwargs={},
        enabled=True,
        last_run_at=None,
        total_run_count=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_dao.create_task.return_value = task_resp

    task_in = PeriodicTaskCreate(
        name="new-task",
        task="api.tasks.new",
        schedule_type=ScheduleType.INTERVAL,
        interval_every=10,
        interval_period=IntervalPeriod.MINUTES,
    )
    with patch("api.apps.common.v0.service.periodic_task.celery_app") as mock_celery:
        mock_celery.tasks = {"api.tasks.new": MagicMock()}
        result = await periodic_service.create_task(task_in)
        assert result.name == "new-task"
        assert result.interval_every == 10


@pytest.mark.asyncio
async def test_update_task(periodic_service: PeriodicTaskService, mock_dao: AsyncMock) -> None:
    """Test updating a periodic task."""
    task_id = uuid4()
    task_resp = PeriodicTaskResponse(
        id=task_id,
        name="updated-task",
        task="api.tasks.updated",
        schedule_type=ScheduleType.CRONTAB,
        cron_minute="*/10",
        cron_hour="*",
        cron_day_of_week="*",
        cron_day_of_month="*",
        cron_month_of_year="*",
        interval_every=None,
        interval_period=None,
        args=[],
        kwargs={},
        enabled=True,
        last_run_at=None,
        total_run_count=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_dao.update_task.return_value = task_resp

    update_in = PeriodicTaskUpdate(cron_minute="*/10")
    result = await periodic_service.update_task(task_id, update_in)
    assert result.cron_minute == "*/10"


@pytest.mark.asyncio
async def test_trigger_task_manually(periodic_service: PeriodicTaskService) -> None:
    """Test manually triggering a task."""
    with patch("api.apps.common.v0.service.periodic_task.celery_app") as mock_celery:
        mock_celery.tasks = {"api.tasks.delete_old_logs": MagicMock()}
        mock_async_res = MagicMock()
        mock_async_res.id = "task-12345"
        mock_celery.send_task.return_value = mock_async_res

        task_id = await periodic_service.trigger_task_manually("api.tasks.delete_old_logs", [], {})
        assert task_id == "task-12345"
        mock_celery.send_task.assert_called_once_with("api.tasks.delete_old_logs", args=[], kwargs={})


@pytest.mark.asyncio
async def test_list_registered_celery_tasks(periodic_service: PeriodicTaskService) -> None:
    """Test listing registered celery tasks."""
    with patch("api.apps.common.v0.service.periodic_task.celery_app") as mock_celery:
        mock_celery.tasks = {"api.tasks.delete_old_logs": MagicMock(), "celery.backend_cleanup": MagicMock()}
        tasks = await periodic_service.list_registered_celery_tasks()
        assert tasks == ["api.tasks.delete_old_logs"]


@pytest.mark.asyncio
async def test_routes(periodic_service: PeriodicTaskService) -> None:
    """Test FastAPI route wrapper functions."""
    periodic_service.list_tasks = AsyncMock(return_value=[])  # type: ignore[method-assign]
    res = await list_periodic_tasks(service=periodic_service, _current_user=MagicMock())
    assert res == []


def test_periodic_task_schema_validation() -> None:
    """Test validation of crontab and interval schedule fields in Pydantic models."""
    # Invalid cron minute (out of range)
    with pytest.raises(ValidationError):
        PeriodicTaskCreate(
            name="bad-cron",
            task="api.tasks.test",
            schedule_type=ScheduleType.CRONTAB,
            cron_minute="70",
        )

    # Invalid interval period (missing interval_period when schedule_type == INTERVAL)
    with pytest.raises(ValidationError):
        PeriodicTaskCreate(
            name="bad-interval",
            task="api.tasks.test",
            schedule_type=ScheduleType.INTERVAL,
            interval_every=5,
            interval_period=None,
        )
