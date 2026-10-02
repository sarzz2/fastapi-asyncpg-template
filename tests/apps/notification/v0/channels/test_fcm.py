from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from api.apps.notification.v0.channels.fcm import FCMChannel
from api.apps.notification.v0.schemas import DeviceResponse, NotificationSchema, NotificationType
from api.core.database import DataBase


@pytest.mark.asyncio
async def test_fcm_channel_send() -> None:
    """Test FCMChannel.send triggers Celery worker task when active devices exist."""
    mock_db = AsyncMock(spec=DataBase)
    channel = FCMChannel(db=mock_db)
    user_id = uuid4()
    notification = NotificationSchema(
        type=NotificationType.INFO,
        message="Push message",
        subject="Alert",
        metadata={"key": "val"},
    )

    device = DeviceResponse(
        id=uuid4(),
        user_id=user_id,
        fcm_token="token_1234567890",
        platform="ios",
        device_name="iPhone",
        is_active=True,
        created_at=None,
        last_used_at=None,
    )

    with patch(
        "api.apps.notification.v0.dao.device.DeviceDAO.get_active_devices_by_user",
        new=AsyncMock(return_value=[device]),
    ):
        with patch("api.apps.notification.v0.channels.fcm.send_fcm_push_worker_task.delay") as mock_delay:
            await channel.send(user_id, notification)
            mock_delay.assert_called_once_with(
                tokens=["token_1234567890"],
                title="Alert",
                body="Push message",
                data={"key": "val"},
            )


@pytest.mark.asyncio
async def test_fcm_channel_broadcast() -> None:
    """Test FCMChannel.broadcast triggers Celery worker task across all active tokens."""
    mock_db = AsyncMock(spec=DataBase)
    channel = FCMChannel(db=mock_db)
    notification = NotificationSchema(
        type=NotificationType.INFO,
        message="Broadcast push",
        subject="Maintenance Notice",
        metadata={"notice_id": "1"},
    )

    with patch(
        "api.apps.notification.v0.dao.device.DeviceDAO.get_all_active_tokens",
        new=AsyncMock(return_value=["token_1", "token_2"]),
    ):
        with patch("api.apps.notification.v0.channels.fcm.send_fcm_push_worker_task.delay") as mock_delay:
            await channel.broadcast(notification)
            mock_delay.assert_called_once_with(
                tokens=["token_1", "token_2"],
                title="Maintenance Notice",
                body="Broadcast push",
                data={"notice_id": "1"},
            )
