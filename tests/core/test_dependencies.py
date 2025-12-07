# pylint: disable=redefined-outer-name
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import SecurityScopes

from api.core.dependencies import get_current_user, get_sudo_user


@pytest.fixture
def mock_token_verification() -> Generator[MagicMock, None, None]:
    """Mock token verification."""
    with patch("api.core.dependencies.verify_token") as mock_verify_token:
        yield mock_verify_token


@pytest.fixture
def mock_user_service() -> MagicMock:
    """Mock user service."""
    return MagicMock()


@pytest.mark.asyncio
async def test_get_current_user_valid(mock_token_verification: MagicMock, mock_user_service: MagicMock) -> None:
    """Test get_current_user with valid token."""
    mock_token = MagicMock()
    mock_token.credentials = "valid_token"
    mock_token_verification.return_value = MagicMock(id="user_id", scopes=[], token_version=1)

    mock_user = MagicMock()
    mock_user.id = "user_id"
    mock_user.token_version = 1
    mock_user_service.get_user_by_id = AsyncMock(return_value=mock_user)

    scopes = SecurityScopes()
    # mock redis
    mock_redis = AsyncMock()

    user = await get_current_user(scopes, token=mock_token, user_service=mock_user_service, redis=mock_redis)
    assert user.id == "user_id"


@pytest.mark.asyncio
async def test_get_current_user_scope_error(mock_token_verification: MagicMock, mock_user_service: MagicMock) -> None:
    """Test get_current_user with insufficient scopes."""
    mock_token = MagicMock()
    mock_token.credentials = "valid_token"
    mock_token_verification.return_value = MagicMock(id="user_id", scopes=[], token_version=1)

    scopes = SecurityScopes(scopes=["admin"])
    mock_redis = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await get_current_user(scopes, token=mock_token, user_service=mock_user_service, redis=mock_redis)
    assert "Not enough permissions" in exc.value.detail


@pytest.mark.asyncio
async def test_get_sudo_user_valid(mock_token_verification: MagicMock, mock_user_service: MagicMock) -> None:
    """Test get_sudo_user with valid sudo token."""
    mock_token = MagicMock()
    mock_token.credentials = "sudo_token"

    # Mock return of verify_token to have type="sudo"
    mock_token_verification.return_value = MagicMock(id="user_id", type="sudo")

    mock_user_service.get_user_by_id = AsyncMock(return_value=MagicMock(id="user_id"))
    mock_redis = AsyncMock()

    user = await get_sudo_user(token=mock_token, user_service=mock_user_service, redis=mock_redis)
    assert user.id == "user_id"


@pytest.mark.asyncio
async def test_get_sudo_user_wrong_type(mock_token_verification: MagicMock, mock_user_service: MagicMock) -> None:
    """Test get_sudo_user with wrong token type."""
    mock_token = MagicMock()
    mock_token.credentials = "access_token"

    # type is access, not sudo
    mock_token_verification.return_value = MagicMock(id="user_id", type="access")

    mock_user_service.get_user_by_id = AsyncMock(return_value=MagicMock(id="user_id"))
    mock_redis = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await get_sudo_user(token=mock_token, user_service=mock_user_service, redis=mock_redis)
    assert "Sudo access required" in exc.value.detail
