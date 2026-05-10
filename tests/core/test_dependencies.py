# pylint: disable=redefined-outer-name
"""Tests for api/core/dependencies.py coverage gaps."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import SecurityScopes

from api.apps.user.v0.schemas.auth import TokenData
from api.core.dependencies import get_current_user, get_sudo_user


@pytest.fixture
def mock_user_service() -> AsyncMock:
    """Mock user service."""
    return AsyncMock()


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock redis client."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_get_current_user_token_id_none(mock_user_service: AsyncMock, mock_redis: AsyncMock) -> None:
    """Test get_current_user raises when token_data.id is None."""
    token = MagicMock()
    token.credentials = "test_token"

    mock_token_data = TokenData(username="user", exp=123, jti="jti", id=None)

    with patch("api.core.dependencies.verify_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = mock_token_data

        with pytest.raises(HTTPException) as exc:
            await get_current_user(
                SecurityScopes([]),
                token,
                mock_user_service,
                mock_redis,
            )

        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_user_none(mock_user_service: AsyncMock, mock_redis: AsyncMock) -> None:
    """Test get_current_user raises when user is None."""
    token = MagicMock()
    token.credentials = "test_token"
    user_id = uuid4()

    mock_token_data = TokenData(username="user", exp=123, jti="jti", id=user_id, token_version=1)

    mock_user_service.get_user_by_id.return_value = None

    with patch("api.core.dependencies.verify_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = mock_token_data

        with pytest.raises(HTTPException) as exc:
            await get_current_user(
                SecurityScopes([]),
                token,
                mock_user_service,
                mock_redis,
            )

        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_token_version_mismatch(mock_user_service: AsyncMock, mock_redis: AsyncMock) -> None:
    """Test get_current_user raises 401 when token version mismatches."""
    token = MagicMock()
    token.credentials = "test_token"
    user_id = uuid4()

    mock_token_data = TokenData(username="user", exp=123, jti="jti", id=user_id, token_version=1)

    mock_user = MagicMock()
    mock_user.token_version = 2  # Different from token

    mock_user_service.get_user_by_id.return_value = mock_user

    with patch("api.core.dependencies.verify_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = mock_token_data

        with pytest.raises(HTTPException) as exc:
            await get_current_user(
                SecurityScopes([]),
                token,
                mock_user_service,
                mock_redis,
            )

        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_sudo_user_token_id_none(mock_user_service: AsyncMock, mock_redis: AsyncMock) -> None:
    """Test get_sudo_user raises when token_data.id is None."""
    token = MagicMock()
    token.credentials = "test_token"

    mock_token_data = TokenData(username="user", exp=123, jti="jti", id=None, type="sudo")

    with patch("api.core.dependencies.verify_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = mock_token_data

        with pytest.raises(HTTPException) as exc:
            await get_sudo_user(token, mock_user_service, mock_redis)

        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_sudo_user_user_none(mock_user_service: AsyncMock, mock_redis: AsyncMock) -> None:
    """Test get_sudo_user raises when user is None."""
    token = MagicMock()
    token.credentials = "test_token"
    user_id = uuid4()

    mock_token_data = TokenData(username="user", exp=123, jti="jti", id=user_id, type="sudo")

    mock_user_service.get_user_by_id.return_value = None

    with patch("api.core.dependencies.verify_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = mock_token_data

        with pytest.raises(HTTPException) as exc:
            await get_sudo_user(token, mock_user_service, mock_redis)

        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_sudo_user_jwt_error(mock_user_service: AsyncMock, mock_redis: AsyncMock) -> None:
    """Test get_sudo_user raises 401 on JWTError."""
    token = MagicMock()
    token.credentials = "test_token"

    with patch("api.core.dependencies.verify_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.side_effect = jwt.PyJWTError("Invalid token")

        with pytest.raises(HTTPException) as exc:
            await get_sudo_user(token, mock_user_service, mock_redis)

        assert exc.value.status_code == 401
