from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from api.apps.common.v0.dao.dead_letter_task import DeadLetterTaskDAO
from api.apps.common.v0.schemas.dead_letter_task import DLQTaskFilter, DLQUpdatePayload
from api.apps.common.v0.service.dead_letter_task import DeadLetterTaskService
from api.core.celery_app import AsyncBaseTask
from api.core.database import DataBase


def test_async_base_task_retry_configuration() -> None:
    """Verify AsyncBaseTask contains default retry settings (exponential backoff & jitter)."""
    assert AsyncBaseTask.max_retries == 3
    assert AsyncBaseTask.retry_backoff is True
    assert AsyncBaseTask.retry_backoff_max == 600
    assert AsyncBaseTask.retry_jitter is True
    assert Exception in AsyncBaseTask.autoretry_for


@pytest.mark.asyncio
async def test_dlq_dao_crud(db_session: DataBase) -> None:
    """Test DAO operations: insertion, listing, updating payloads, discarding, deleting."""
    dao = DeadLetterTaskDAO(db=db_session)
    task_id_str = str(uuid4())

    # Insert test failure entry
    query = """
        INSERT INTO dead_letter_tasks (
            task_id, task_name, queue, args, kwargs, exception_type, exception_message, traceback
        ) VALUES (
            $1, 'send_notification_task', 'default', '["user_123"]'::jsonb, '{"retry": true}'::jsonb,
            'ValueError', 'Invalid user ID', 'Traceback example...'
        ) RETURNING id;
    """
    row = await db_session.fetch(query, task_id_str, fetch_row=True)
    assert row is not None
    dlq_id = row["id"]

    # List tasks
    filter_opts = DLQTaskFilter(task_name="send_notification_task")
    tasks = await dao.list_tasks(filter_opts)
    count = await dao.count_tasks(filter_opts)
    assert count >= 1
    assert any(t.id == dlq_id for t in tasks)

    # Get by ID
    single = await dao.get_task_by_id(dlq_id)
    assert single is not None
    assert single.task_name == "send_notification_task"
    assert single.args == ["user_123"]

    # Update payload
    count = await dao.update_task_payload(DLQUpdatePayload(args=["user_456"], kwargs={"retry": False}), task_id=dlq_id)
    assert count == 1

    single_after_update = await dao.get_task_by_id(dlq_id)
    assert single_after_update is not None
    assert single_after_update.args == ["user_456"]
    assert single_after_update.kwargs == {"retry": False}

    # Fetch and delete (simulate retriggering)
    deleted_tasks = await dao.fetch_and_delete_tasks(task_ids=[dlq_id])
    assert len(deleted_tasks) == 1
    assert deleted_tasks[0].id == dlq_id

    # Verify task is deleted from DB
    check = await dao.get_task_by_id(dlq_id)
    assert check is None


@pytest.mark.asyncio
async def test_dlq_bulk_operations(db_session: DataBase) -> None:
    """Test bulk payload updates, bulk discard, and statistics."""
    dao = DeadLetterTaskDAO(db=db_session)

    # Insert 3 test tasks
    for _i in range(3):
        await db_session.execute(
            """
            INSERT INTO dead_letter_tasks (
                task_id, task_name, queue, args, kwargs, exception_type, exception_message
            ) VALUES (
                $1, 'broadcast_task', 'default', '[]'::jsonb, '{"idx": 1}'::jsonb,
                'TimeoutError', 'Connection timeout'
            );
            """,
            str(uuid4()),
        )

    # Bulk update payloads
    bulk_update_res = await dao.update_task_payload(
        DLQUpdatePayload(
            task_name="broadcast_task",
            queue="priority",
            kwargs={"idx": 2, "updated": True},
            merge_kwargs=True,
        )
    )
    assert bulk_update_res >= 3

    # Check updated queue
    tasks = await dao.list_tasks(DLQTaskFilter(task_name="broadcast_task"))
    assert all(t.queue == "priority" for t in tasks)

    # Check statistics
    stats = await dao.get_statistics()
    assert stats.total_count >= 3
    assert "broadcast_task" in stats.by_task_name

    # Bulk delete
    delete_res = await dao.delete_tasks(task_name="broadcast_task")
    assert delete_res >= 3


@pytest.mark.asyncio
async def test_dlq_service_retrigger(db_session: DataBase) -> None:
    """Test service single and bulk retriggering."""
    dao = DeadLetterTaskDAO(db=db_session)
    service = DeadLetterTaskService(dao=dao)

    # Insert test task
    row = await db_session.fetch(
        """
        INSERT INTO dead_letter_tasks (
            task_id, task_name, queue, args, kwargs, exception_type
        ) VALUES (
            $1, 'send_notification_task', 'default', '["hello"]'::jsonb, '{}'::jsonb, 'RuntimeError'
        ) RETURNING id;
        """,
        str(uuid4()),
        fetch_row=True,
    )
    assert row is not None
    dlq_id = row["id"]

    # Retrigger single task
    res = await service.retrigger_tasks(task_id=dlq_id)
    assert "retriggered" in res.message.lower()
    assert res.affected_count == 1

    # Verify DLQ entry was deleted upon retrigger
    check = await dao.get_task_by_id(dlq_id)
    assert check is None


@pytest.mark.asyncio
async def test_dlq_clean_old_tasks_task(db_session: DataBase) -> None:
    """Test clean_old_dlq_tasks task purging items older than 30 days."""
    dao = DeadLetterTaskDAO(db=db_session)

    # Insert an old task failed 31 days ago
    old_date = datetime.now(timezone.utc) - timedelta(days=31)
    await db_session.execute(
        """
        INSERT INTO dead_letter_tasks (
            task_id, task_name, queue, failed_at, created_at
        ) VALUES ($1, 'old_task', 'default', $2, $2);
        """,
        str(uuid4()),
        old_date,
    )

    deleted_count = await dao.delete_old_tasks(days=30)
    assert deleted_count >= 1
