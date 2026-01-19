# pylint: disable=import-outside-toplevel
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from api.apps.notification.schemas import NotificationType

# NOTE: We do NOT import tasks at top level to allow patching decorators


def test_send_notification_task() -> None:
    """Test the send_notification_task wrapper."""
    user_id = uuid4()
    message = "Test message"

    with patch("api.core.celery_app.celery_app.task", side_effect=lambda *args, **kwargs: lambda func: func):
        import importlib

        from api.apps.notification import tasks

        importlib.reload(tasks)

        with patch("api.apps.notification.tasks.notification_service") as mock_service:
            mock_service.notify = AsyncMock()

            mock_self = MagicMock()
            mock_loop = MagicMock()
            mock_self.loop = mock_loop

            tasks.send_notification_task(
                mock_self, str(user_id), message, NotificationType.INFO.value, "Subject", {"key": "value"}
            )

            mock_loop.run_until_complete.assert_called_once()

            args = mock_loop.run_until_complete.call_args[0]
            coro = args[0]

            import asyncio

            asyncio.run(coro)

            mock_service.notify.assert_awaited_once_with(
                user_id=user_id,
                message=message,
                notification_type=NotificationType.INFO,
                subject="Subject",
                metadata={"key": "value"},
            )


def test_send_notification_task_error() -> None:
    """Test error handling in send_notification_task."""
    user_id = uuid4()

    with patch("api.core.celery_app.celery_app.task", side_effect=lambda *args, **kwargs: lambda func: func):
        import importlib

        from api.apps.notification import tasks

        importlib.reload(tasks)

        with (
            patch("api.apps.notification.tasks.notification_service"),
            patch("api.apps.notification.tasks.log") as mock_log,
        ):
            mock_self = MagicMock()
            mock_self.loop.run_until_complete.side_effect = Exception("Boom")

            tasks.send_notification_task(mock_self, str(user_id), "msg")

            mock_log.error.assert_called_once()


def test_broadcast_notification_task() -> None:
    """Test the broadcast_notification_task wrapper."""
    message = "Broadcast message"

    with patch("api.core.celery_app.celery_app.task", side_effect=lambda *args, **kwargs: lambda func: func):
        import importlib

        from api.apps.notification import tasks

        importlib.reload(tasks)

        with patch("api.apps.notification.tasks.notification_service") as mock_service:
            mock_service.broadcast_all = AsyncMock()

            mock_self = MagicMock()
            mock_loop = MagicMock()
            mock_self.loop = mock_loop

            tasks.broadcast_notification_task(
                mock_self, message, NotificationType.WARNING.value, "Subject", {"key": "data"}
            )

            mock_loop.run_until_complete.assert_called_once()

            args = mock_loop.run_until_complete.call_args[0]
            coro = args[0]

            import asyncio

            asyncio.run(coro)

            mock_service.broadcast_all.assert_awaited_once_with(
                message=message, notification_type=NotificationType.WARNING, subject="Subject", metadata={"key": "data"}
            )


def test_broadcast_notification_task_error() -> None:
    """Test error handling in broadcast_notification_task."""
    with patch("api.core.celery_app.celery_app.task", side_effect=lambda *args, **kwargs: lambda func: func):
        import importlib

        from api.apps.notification import tasks

        importlib.reload(tasks)

        with (
            patch("api.apps.notification.tasks.notification_service"),
            patch("api.apps.notification.tasks.log") as mock_log,
        ):
            mock_self = MagicMock()
            mock_self.loop.run_until_complete.side_effect = Exception("Boom")

            tasks.broadcast_notification_task(mock_self, "msg")

            mock_log.error.assert_called_once()
