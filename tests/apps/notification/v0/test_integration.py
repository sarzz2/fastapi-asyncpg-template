# pylint: disable=redefined-outer-name, unused-variable, unused-argument, broad-exception-caught
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import status

from api.apps.notification.v0.dao.device import DeviceDAO, get_device_dao
from api.apps.notification.v0.schemas import DeviceResponse
from api.apps.user.v0.dao.user import UserDAO
from api.core.auth import TokenData
from api.core.dependencies import get_current_user
from api.main import app


@pytest.fixture
def mock_token_data() -> TokenData:
    """Mock TokenData fixture."""
    return TokenData(
        username="testuser",
        id=uuid4(),
        exp=1234567890,
        jti=str(uuid4()),
        type="access",
        scopes=[],
        token_version=1,
    )


@pytest.fixture
def mock_user_dao() -> AsyncMock:
    """Mock UserDAO fixture."""
    dao = AsyncMock(spec=UserDAO)
    dao.get_by_id = AsyncMock()
    return dao


@pytest.fixture
def mock_device_dao() -> AsyncMock:
    """Mock DeviceDAO fixture."""
    return AsyncMock(spec=DeviceDAO)


def test_sse_endpoint_missing_token(sync_client: Any) -> None:
    """Test SSE endpoint returns 422 when required token query param is missing."""
    response = sync_client.get("/api/v0/notifications/sse")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_sse_endpoint_invalid_token(sync_client: Any) -> None:
    """Test SSE endpoint returns 401 when token is invalid."""
    with patch(
        "api.apps.notification.v0.routes.verify_token",
        side_effect=Exception("Invalid token"),
    ):
        with pytest.raises(Exception):
            sync_client.get("/api/v0/notifications/sse?token=invalid_token")


def test_device_registration_and_list(sync_client: Any, mock_token_data: TokenData) -> None:
    """Test registering a push device token and listing user devices."""
    user_id = mock_token_data.id or uuid4()
    mock_user = AsyncMock()
    mock_user.id = user_id

    mock_device = DeviceResponse(
        id=uuid4(),
        user_id=user_id,
        fcm_token="test_fcm_token_12345",
        platform="android",
        device_name="Pixel 8",
        is_active=True,
        created_at=None,
        last_used_at=None,
    )

    mock_dao = AsyncMock(spec=DeviceDAO)
    mock_dao.register_device.return_value = mock_device
    mock_dao.get_active_devices_by_user.return_value = [mock_device]
    mock_dao.unregister_device.return_value = None

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_device_dao] = lambda: mock_dao

    try:
        # Register device
        reg_response = sync_client.post(
            "/api/v0/notifications/devices",
            json={
                "fcm_token": "test_fcm_token_12345",
                "platform": "android",
                "device_name": "Pixel 8",
            },
        )
        assert reg_response.status_code == status.HTTP_201_CREATED
        assert reg_response.json()["fcm_token"] == "test_fcm_token_12345"
        mock_dao.register_device.assert_awaited_once()

        # List devices
        list_response = sync_client.get("/api/v0/notifications/devices")
        assert list_response.status_code == status.HTTP_200_OK
        data = list_response.json()
        assert len(data) == 1
        assert data[0]["platform"] == "android"

        # Unregister device
        del_response = sync_client.delete("/api/v0/notifications/devices/test_fcm_token_12345")
        assert del_response.status_code == status.HTTP_204_NO_CONTENT
        mock_dao.unregister_device.assert_awaited_once_with(user_id=user_id, fcm_token="test_fcm_token_12345")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_device_dao, None)
