from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from api.apps.notification.v0.listeners.two_factor import on_two_factor_disabled, on_two_factor_enabled
from api.apps.notification.v0.schemas import NotificationType
from api.core.events.constants import EventNames
from api.core.events.schema import ApplicationEvent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("listener", "event_name", "expected_type", "expected_subject"),
    [
        (
            on_two_factor_enabled,
            EventNames.USER_2FA_ENABLED,
            NotificationType.SUCCESS,
            "Security Alert: Two-Factor Authentication Enabled",
        ),
        (
            on_two_factor_disabled,
            EventNames.USER_2FA_DISABLED,
            NotificationType.WARNING,
            "Security Alert: Two-Factor Authentication Disabled",
        ),
    ],
)
async def test_two_factor_listeners_dispatch_email(
    listener: object,
    event_name: EventNames,
    expected_type: NotificationType,
    expected_subject: str,
) -> None:
    """Verify 2FA event listeners dispatch notifications with standard email template."""
    event = ApplicationEvent(
        event_name=event_name,
        payload={
            "user_id": str(uuid4()),
            "email": "user2fa@example.com",
            "username": "user2fa",
        },
    )

    with patch(
        "api.apps.notification.v0.listeners.two_factor.dispatch_user_notification",
        new_callable=AsyncMock,
    ) as mock_dispatch:
        assert callable(listener)
        await listener(event)
        assert mock_dispatch.await_count == 1
        assert mock_dispatch.await_args is not None
        kwargs = mock_dispatch.await_args.kwargs
        assert kwargs["event"] == event
        assert kwargs["notification_type"] == expected_type
        assert kwargs["subject"] == expected_subject
        assert kwargs["template_path"] == "email/notification.html"
        assert "Two-Factor Authentication" in kwargs["message"]
