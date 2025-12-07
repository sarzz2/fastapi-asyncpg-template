# pylint: disable=redefined-outer-name
from datetime import datetime
from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.apps.user.schemas.user import UserCreate
from api.apps.user.v0.service.auth import AuthService
from api.apps.user.v0.service.user import UserService
from api.core.auth import get_password_hash


@pytest.fixture(autouse=True)
def mock_s3_url() -> Generator[None, None, None]:
    """Mock s3 url."""
    with patch("api.apps.user.schemas.user.generate_file_url", return_value="http://mock_url"):
        yield


@pytest.fixture
def mock_user_dao() -> MagicMock:
    """Mock user dao."""
    mock = MagicMock()
    mock.get_by_google_sub = AsyncMock()
    mock.get_by_email = AsyncMock()
    mock.get_by_username = AsyncMock()
    mock.create_user = AsyncMock()
    mock.create_user_oauth = AsyncMock()
    mock.create_user_oauth = AsyncMock()
    mock.add_identity = AsyncMock()
    mock.revoke_user_session = AsyncMock()
    mock.upsert_user_session = AsyncMock()
    return mock


@pytest.fixture
def mock_role_dao() -> MagicMock:
    """Mock role dao."""
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock redis."""
    mock = AsyncMock()
    mock.set = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_auth_service_handle_google_oauth(
    mock_user_dao: MagicMock, mock_role_dao: MagicMock, mock_redis: AsyncMock
) -> None:
    """Test auth service handle google oauth."""
    service = AuthService(mock_user_dao, mock_role_dao, mock_redis)

    # Case 1: Existing user by sub
    user_info: dict[str, Any] = {"sub": "google_123", "email": "test@example.com"}
    mock_user = MagicMock()
    mock_user_dao.get_by_google_sub.return_value = mock_user

    result = await service.handle_google_oauth(user_info)
    assert result == mock_user

    # Case 2: Link by email
    mock_user_dao.get_by_google_sub.return_value = None
    mock_user_dao.get_by_email.return_value = mock_user
    user_info["email_verified"] = True

    result = await service.handle_google_oauth(user_info)
    assert result == mock_user
    mock_user_dao.add_identity.assert_called()

    # Case 3: Create new user
    mock_user_dao.get_by_email.return_value = None
    mock_user_dao.get_by_username.return_value = None  # username avail
    mock_user_dao.create_user_oauth.return_value = mock_user

    result = await service.handle_google_oauth(user_info)
    assert result == mock_user
    mock_user_dao.create_user_oauth.assert_called()


@pytest.mark.asyncio
async def test_user_service_create_user(mock_user_dao: MagicMock, mock_redis: AsyncMock) -> None:
    """Test user service create user."""
    service = UserService(mock_user_dao, mock_redis)

    user_in = UserCreate(username="u", email="e@e.com", password=None, full_name="f", is_active=True)
    with pytest.raises(ValueError):
        await service.create_user(user_in)

    # Success
    user_in = UserCreate(username="u", email="e@e.com", password="pass", full_name="f", is_active=True)
    mock_user = MagicMock()
    mock_user_dao.create_user.return_value = mock_user

    # If we don't mock UserData, we need mock_user to have fields
    mock_user.id = uuid4()
    mock_user.username = "u"
    mock_user.email = "e@e.com"
    mock_user.is_active = True
    mock_user.is_superuser = False
    mock_user.is_superuser = False
    mock_user.full_name = "f"
    mock_user.created_at = datetime.now()
    mock_user.updated_at = datetime.now()
    mock_user.roles = []
    mock_user.token_version = 1
    mock_user.profile_picture_url = None
    mock_user.hashed_password = "hash"

    result = await service.create_user(user_in)
    assert result.username == "u"


@pytest.mark.asyncio
async def test_auth_service_authenticate(
    mock_user_dao: MagicMock, mock_role_dao: MagicMock, mock_redis: AsyncMock
) -> None:
    """
    Test auth service authenticate.
    Args:
        mock_user_dao: Mock user dao.
        mock_role_dao: Mock role dao.
        mock_redis: Mock redis.
    Returns:
        None
    """
    service = AuthService(mock_user_dao, mock_role_dao, mock_redis)

    mock_user = MagicMock()
    mock_user.hashed_password = get_password_hash("pass")
    mock_user.username = "u"
    mock_user.email = "e@e.com"
    mock_user.id = uuid4()
    mock_user.token_version = 1
    mock_user.roles = []
    mock_user.is_active = True
    mock_user.profile_picture_url = None
    mock_user.full_name = "f"
    mock_user.created_at = datetime.now()
    mock_user.hashed_password = "hash"
    mock_user.hashed_password = get_password_hash("pass")

    mock_user_dao.get_by_username.return_value = mock_user

    request = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers.get.return_value = "mozilla"

    # Success
    response = await service.authenticate_user("u", "pass", request)
    assert response.user.username == "u"
    assert response.token.access_token

    # Fail
    with pytest.raises(HTTPException):
        await service.authenticate_user("u", "wrong", request)


@pytest.mark.asyncio
async def test_user_service_revoke_session(mock_user_dao: MagicMock, mock_redis: AsyncMock) -> None:
    """
    Test user service revoke session.
    Args:
        mock_user_dao: Mock user dao.
        mock_redis: Mock redis.
    Returns:
        None
    """
    service = UserService(mock_user_dao, mock_redis)
    mock_user_dao.revoke_user_session.return_value = 3600

    await service.revoke_user_session(uuid4(), "jti")

    assert mock_redis.set.call_count == 2
