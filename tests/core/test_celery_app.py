import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.core.celery_app import AsyncBaseTask, autodiscover_tasks, init_worker_process, shutdown_worker_process


def test_autodiscover_tasks() -> None:
    """
    Verify that tasks are correctly discovered from the apps directory.
    """
    with (
        patch("os.listdir") as mock_listdir,
        patch("os.path.isdir") as mock_isdir,
        patch("os.path.exists") as mock_exists,
    ):
        # Mock a typical directory structure
        mock_isdir.side_effect = lambda p: True
        mock_listdir.side_effect = lambda p: ["user"] if "apps" in p and "tasks" not in p else ["test_task.py"]
        mock_exists.return_value = True

        tasks = autodiscover_tasks()

        assert "api.apps.user.tasks" in tasks
        assert "api.tasks.test_task" in tasks


@pytest.mark.asyncio
async def test_worker_process_lifecycle() -> None:
    """
    Verify the full lifecycle of worker process: initialization and shutdown.
    """
    with (
        patch("api.core.celery_app.celery_app") as mock_app,
        patch("api.core.celery_app.DataBase") as mock_db_cls,
        patch("api.core.celery_app.RedisClient") as mock_redis_cls,
        patch("asyncio.new_event_loop") as mock_new_loop,
        patch("asyncio.set_event_loop"),
    ):
        mock_loop = MagicMock()
        mock_new_loop.return_value = mock_loop

        mock_db = AsyncMock()
        mock_db_cls.return_value = mock_db

        mock_redis = AsyncMock()
        mock_redis_cls.return_value = mock_redis

        # 1. Initialize worker
        init_worker_process()

        # Verify init
        assert mock_app.main_loop == mock_loop
        assert mock_app.db_instance == mock_db
        assert mock_app.redis_instance == mock_redis
        mock_loop.run_until_complete.assert_called()
        mock_db.create_pool.assert_called_once()
        mock_redis.connect.assert_called_once()

        # 2. Shutdown worker
        mock_loop.run_until_complete.reset_mock()
        shutdown_worker_process()

        # Verify cleanup
        mock_loop.run_until_complete.assert_called()
        mock_db.close_pool.assert_called_once()
        mock_redis.close.assert_called_once()

        # Prevent RuntimeWarning for unawaited mock coroutines
        for m in [mock_db.create_pool, mock_redis.connect, mock_db.close_pool, mock_redis.close]:
            coro = m.return_value
            if asyncio.iscoroutine(coro):
                coro.close()


def test_async_base_task_properties() -> None:
    """
    Verify property accessors in AsyncBaseTask.
    """
    task = AsyncBaseTask()
    task.app = MagicMock()

    # Test loop property
    task.app.main_loop = "mock_loop"
    assert task.loop == "mock_loop"

    # Test loop property error when not initialized
    del task.app.main_loop
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = task.loop

    # Test DB and Redis property accessors
    task.app.db_instance = "mock_db"
    assert task.db == "mock_db"

    task.app.redis_instance = "mock_redis"
    assert task.redis == "mock_redis"
