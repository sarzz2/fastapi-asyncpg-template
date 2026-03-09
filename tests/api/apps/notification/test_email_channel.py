from unittest.mock import patch
from uuid import uuid4

import pytest

from api.apps.notification.v0.channels.email import EmailChannel
from api.apps.notification.v0.schemas import NotificationSchema, NotificationType


@pytest.fixture
def notification() -> NotificationSchema:
    """Test notification."""
    return NotificationSchema(
        type=NotificationType.INFO,
        message="Test Message",
        subject="Test Subject",
        metadata={
            "email": ["test1@example.com", "test2@example.com"],
            "cc": ["cc1@example.com"],
            "bcc": ["bcc1@example.com"],
            "attachments": [{"content": "YmFzZTY0dGVzdA==", "type": "text/plain", "filename": "test.txt"}],
        },
    )


@pytest.mark.asyncio
async def test_email_channel_send_success(notification: NotificationSchema) -> None:  # pylint: disable=redefined-outer-name, unused-argument
    """Test that email_channel.send correctly extracts lists/attachments and triggers Celery task"""
    channel = EmailChannel()
    user_id = uuid4()

    with patch("api.apps.notification.tasks.send_email_worker_task.delay") as mock_delay:
        await channel.send(user_id, notification)

        # Verify Celery task was called
        mock_delay.assert_called_once()

        # Check the payload passed to delay()
        kwargs = mock_delay.call_args[1]
        assert kwargs["to_email"] == ["test1@example.com", "test2@example.com"]
        assert kwargs["subject"] == "Test Subject"
        assert "Test Message" in kwargs["html_content"]
        assert "Test Subject" in kwargs["html_content"]
        assert kwargs["cc_emails"] == ["cc1@example.com"]
        assert kwargs["bcc_emails"] == ["bcc1@example.com"]
        assert len(kwargs["attachments"]) == 1
        assert kwargs["attachments"][0]["filename"] == "test.txt"
