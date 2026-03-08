from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# We use sync_client
from api.apps.user.v0.dao.user import UserDAO, get_user_dao
from api.core.auth import TokenData
from api.main import app

# pylint: disable=redefined-outer-name, unused-variable, unused-argument, broad-exception-caught


@pytest.fixture
def mock_token_data() -> TokenData:
    """Mock TokenData fixture."""
    return TokenData(
        username="testuser",
        id=str(uuid4()),
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


def test_websocket_endpoint_missing_token(sync_client: Any) -> None:  # pylint: disable=redefined-outer-name
    """Test connection with missing token."""
    with pytest.raises(Exception):
        with sync_client.websocket_connect("/api/v0/notifications/ws") as websocket:
            websocket.receive_text()


def test_websocket_endpoint_success(sync_client: Any, mock_token_data: TokenData, mock_user_dao: AsyncMock) -> None:  # pylint: disable=redefined-outer-name
    """Test successful connection and message sending."""
    token = "valid_token"

    # Override dependency for UserDAO
    app.dependency_overrides[get_user_dao] = lambda: mock_user_dao

    try:
        with patch("api.apps.notification.v0.routes.verify_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = mock_token_data
            with patch("api.apps.notification.v0.routes.connection_manager") as mock_manager:
                # Define side effect to accept websocket connection, as connection_manager.connect does this
                async def connect_side_effect(websocket: Any, user_id: Any) -> None:  # pylint: disable=unused-argument
                    await websocket.accept()

                mock_manager.connect = AsyncMock(side_effect=connect_side_effect)
                mock_manager.disconnect = AsyncMock()

                # Setup mock user
                mock_user = AsyncMock()
                mock_user.is_active = True
                mock_user_dao.get_by_id.return_value = mock_user

                with sync_client.websocket_connect(f"/api/v0/notifications/ws?token={token}") as websocket:
                    # Connection established
                    mock_verify.assert_called()
                    # We can verify user_dao call if needed
                    # mock_user_dao.get_by_id.assert_called()

                    websocket.send_text("ping")

                # Disconnect logic happens on exit
    finally:
        app.dependency_overrides.pop(get_user_dao, None)


def test_websocket_endpoint_invalid_token(sync_client: Any) -> None:
    """Test connection with invalid token."""
    token = "invalid"

    with patch("api.apps.notification.v0.routes.verify_token", side_effect=Exception("Invalid")):
        with pytest.raises(Exception):
            with sync_client.websocket_connect(f"/api/v0/notifications/ws?token={token}") as websocket:
                websocket.receive_text()
