from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import HTTPException

from api.constants import TokenTypes
from api.core.auth import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    create_refresh_token,
    create_sudo_token,
    get_password_hash,
    verify_password,
    verify_token,
)


def test_password_hashing() -> None:
    """Test password hashing and verification."""
    password = "secret_password"
    hashed = get_password_hash(password)
    assert verify_password(password, hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password(password, None)


def test_create_access_token() -> None:
    """Test access token creation."""
    data = {"sub": "testuser", "id": "123"}
    token = create_access_token(data)
    assert "token" in token  # It returns a dict
    encoded = token["token"]

    payload = jwt.decode(encoded, SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["sub"] == "testuser"
    assert payload["type"] == TokenTypes.ACCESS.value


def test_create_refresh_token() -> None:
    """Test refresh token creation."""
    data = {"sub": "testuser", "id": "123"}
    refresh = create_refresh_token(data)
    # returns str
    assert isinstance(refresh, str)


def test_create_sudo_token() -> None:
    """Test sudo token creation."""
    data = {"sub": "testuser", "id": "123"}
    sudo = create_sudo_token(data)
    assert isinstance(sudo, str)


@pytest.mark.asyncio
async def test_verify_token_valid() -> None:
    """Test token verification with valid token."""
    data = {"sub": "user", "id": "123e4567-e89b-12d3-a456-426614174000", "scopes": [], "token_version": 1}
    token_dict = create_access_token(data)
    token = token_dict["token"]

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # Not blacklisted

    token_data = await verify_token(token, mock_redis, token_type=TokenTypes.ACCESS.value)
    assert token_data.username == "user"
    assert str(token_data.id) == "123e4567-e89b-12d3-a456-426614174000"


@pytest.mark.asyncio
async def test_verify_token_invalid() -> None:
    """Test token verification with invalid token."""
    mock_redis = AsyncMock()
    with pytest.raises(HTTPException):
        await verify_token("invalid", mock_redis)


@pytest.mark.asyncio
async def test_verify_token_wrong_type() -> None:
    """Test token verification with wrong token type."""
    data = {"sub": "user", "id": "1"}
    token = create_access_token(data)["token"]

    mock_redis = AsyncMock()
    # Expecting refresh, got access
    with pytest.raises(HTTPException):
        await verify_token(token, mock_redis, token_type=TokenTypes.REFRESH.value)


@pytest.mark.asyncio
async def test_verify_token_blacklisted() -> None:
    """Test token verification with blacklisted token."""
    data = {"sub": "user", "id": "1"}
    token = create_access_token(data)["token"]

    mock_redis = AsyncMock()
    mock_redis.get.return_value = "blacklisted"

    with pytest.raises(HTTPException) as exc:
        await verify_token(token, mock_redis)
    assert "revoked" in exc.value.detail


@pytest.mark.asyncio
async def test_verify_refresh_token_blacklisted() -> None:
    """Test refresh token verification with blacklisted token."""
    data = {"sub": "user", "id": "1"}
    token = create_refresh_token(data)

    mock_redis = AsyncMock()
    mock_redis.get.return_value = "blacklisted"

    with pytest.raises(HTTPException) as exc:
        await verify_token(token, mock_redis, token_type=TokenTypes.REFRESH.value)
    assert "revoked" in exc.value.detail


@pytest.mark.asyncio
async def test_verify_sudo_token_blacklisted() -> None:
    """Test sudo token verification with blacklisted token."""
    data = {"sub": "user", "id": "1"}
    token = create_sudo_token(data)

    mock_redis = AsyncMock()
    mock_redis.get.return_value = "blacklisted"

    with pytest.raises(HTTPException) as exc:
        await verify_token(token, mock_redis, token_type=TokenTypes.SUDO.value)
    assert "revoked" in exc.value.detail
