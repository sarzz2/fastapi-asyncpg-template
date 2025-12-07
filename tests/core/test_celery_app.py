from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.core.celery_app import AsyncBaseTask, autodiscover_tasks, init_worker_process, shutdown_worker_process


def test_autodiscover_tasks() -> None:
    """
    Test autodiscover_tasks function.
    """
    with (
        patch("os.listdir") as mock_listdir,
        patch("os.path.isdir") as mock_isdir,
        patch("os.path.exists") as mock_exists,
    ):
        # Mock apps directory structure
        mock_isdir.side_effect = lambda p: True  # All are dirs
        mock_listdir.side_effect = lambda p: ["user"] if "apps" in p and "tasks" not in p else ["test_task.py"]
        mock_exists.return_value = True

        tasks = autodiscover_tasks()
        assert "api.apps.user.tasks" in tasks
        assert "api.tasks.test_task" in tasks


@pytest.mark.asyncio
async def test_init_worker_process() -> None:
    """
    Test init_worker_process function.
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

        init_worker_process()

        assert mock_app.main_loop == mock_loop
        assert mock_app.db_instance == mock_db
        assert mock_app.redis_instance == mock_redis

        mock_loop.run_until_complete.assert_called()
        mock_db.create_pool.assert_called_once()
        mock_redis.connect.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_worker_process() -> None:
    """
    Test shutdown_worker_process function.
    """
    with patch("api.core.celery_app.celery_app") as mock_app:
        mock_loop = MagicMock()
        mock_app.main_loop = mock_loop

        mock_db = AsyncMock()
        mock_app.db_instance = mock_db

        mock_redis = AsyncMock()
        mock_app.redis_instance = mock_redis

        shutdown_worker_process()

        mock_loop.run_until_complete.assert_called()
        mock_db.close_pool.assert_called_once()
        mock_redis.close.assert_called_once()


def test_async_base_task_properties() -> None:
    """
    Test AsyncBaseTask properties.
    """
    task = AsyncBaseTask()
    task.app = MagicMock()

    # Test loop property
    task.app.main_loop = "loop"
    assert task.loop == "loop"

    # Test loop property error
    del task.app.main_loop
    with pytest.raises(RuntimeError):
        _ = task.loop

    # Test db property
    task.app.db_instance = "db"
    assert task.db == "db"

    # Test redis property
    task.app.redis_instance = "redis"
    assert task.redis == "redis"
